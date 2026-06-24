#!/usr/bin/env python3
"""
查漏补缺工具：对比 MasterData 原文与现有翻译，导出待翻译清单。

用法:
    python check_missing.py [masterdata_json] [translation_dir] [mapping_json]

默认参数:
    masterdata_json = E:\\Everything\\data_29_named.json
    translation_dir = translations
    mapping_json    = D:\\AbyssMod\\AbyssMod\\mapping\\master_mapping.json

输出:
    missing/<表名>/zh_Hans.json  — 每张表的待翻译条目（原文留空译文）
    missing/_summary.txt         — 汇总报告
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# 默认路径
DEFAULT_MASTERDATA = r"E:\Everything\data_29_named.json"
DEFAULT_TRANSLATIONS = r"D:\DMM_Translation\dotabyss-translation\translations"
DEFAULT_MAPPING = r"D:\AbyssMod\AbyssMod\mapping\master_mapping.json"

# 表类名 M* → MasterData key m_* 的转换，优先用已知映射
# 因为驼峰转下划线对连续大写（如 NPC）会出错，这里用 data_29 的 key 做权威查找
TABLE_PREFIX_MAP = {
    "MAbilityDetails": "m_ability_details",
    "MCharacterActionSkills": "m_character_action_skills",
    "MCharacterProfiles": "m_character_profiles",
    "MChapterQuests": "m_chapter_quests",
    "MCharacters": "m_characters",
    "MDefendStages": "m_defend_stages",
    "MDictionaryEnemies": "m_dictionary_enemies",
    "MDictionaryEnemyGroups": "m_dictionary_enemy_groups",
    "MDictionaryNonPlayerCharacters": "m_dictionary_non_player_characters",
    "MDisasterBosses": "m_disaster_bosses",
    "MDisasterQuests": "m_disaster_quests",
    "MEnemies": "m_enemies",
    "MEnchantmentDetails": "m_enchantment_details",
    "MEnemySkills": "m_enemy_skills",
    "MGachaGroupMovies": "m_gacha_group_movies",
    "MJobs": "m_jobs",
    "MNetherCodeCategorySkills": "m_nether_code_category_skills",
    "MNetherCodes": "m_nether_codes",
    "MNovelCharacterSkins": "m_novel_character_skins",
    "MNovelCharacters": "m_novel_characters",
    "MNovelEvents": "m_novel_events",
    "MNovelHomes": "m_novel_homes",
    "MNovelMains": "m_novel_mains",
    "MNovelOthers": "m_novel_others",
    "MNovelPrologues": "m_novel_prologues",
    "MPartVoices": "m_part_voices",
    "MPlans": "m_plans",
    "MPreregistTaverns": "m_preregist_taverns",
    "MTavernCards": "m_tavern_cards",
    "MTavernCharacterCards": "m_tavern_character_cards",
    "MTavernDialogue": "m_tavern_dialogue",
    "MAttributeTags": "m_attribute_tags",
}


def load_json(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_table_name(class_name: str, md_keys: set[str]) -> str | None:
    """表类名 M* → m_* key。优先用已知映射，否则尝试驼峰转下划线。"""
    if class_name in TABLE_PREFIX_MAP:
        key = TABLE_PREFIX_MAP[class_name]
        return key if key in md_keys else None
    # 驼峰转下划线兜底：MSomeThing -> m_some_thing
    import re
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
    return snake if snake in md_keys else None


def get_rows(md: dict, table_key: str) -> list:
    rows = md.get(table_key)
    if rows is None:
        return []
    if isinstance(rows, dict) and "rows" in rows:
        rows = rows["rows"]
    return rows if isinstance(rows, list) else []


def collect_field_texts(md: dict, table_key: str, fields: list[str]) -> set[str]:
    """收集某张表指定字段的所有非空字符串原文。"""
    texts = set()
    for row in get_rows(md, table_key):
        if not isinstance(row, dict):
            continue
        for fld in fields:
            v = row.get(fld)
            if isinstance(v, str) and v:
                texts.add(v)
    return texts


def load_translations(trans_dir: Path, dict_name: str) -> dict[str, str]:
    """加载某个翻译字典文件。不存在返回空。"""
    path = trans_dir / dict_name / "zh_Hans.json"
    if not path.exists():
        return {}
    try:
        data = load_json(path)
        # 只保留扁平 string 值
        return {k: v for k, v in data.items() if isinstance(v, str)}
    except Exception:
        return {}


def main():
    args = sys.argv[1:]
    masterdata_path = args[0] if len(args) > 0 else DEFAULT_MASTERDATA
    trans_dir = Path(args[1] if len(args) > 1 else DEFAULT_TRANSLATIONS)
    mapping_path = args[2] if len(args) > 2 else DEFAULT_MAPPING
    if not trans_dir.is_absolute():
        trans_dir = Path(__file__).resolve().parent / trans_dir

    # 1. 读映射配置
    if not Path(mapping_path).exists():
        print(f"错误：找不到映射配置 {mapping_path}")
        sys.exit(1)

    mapping = load_json(mapping_path)
    md_keys = None
    md = None

    # 2. 读 MasterData
    if not Path(masterdata_path).exists():
        print(f"错误：找不到 MasterData {masterdata_path}")
        sys.exit(1)
    md = load_json(masterdata_path)
    md_keys = set(md.keys())

    # 3. 遍历映射，逐表逐字段查漏
    # 导出目录与脚本同目录
    out_dir = Path(__file__).resolve().parent / "missing"
    if out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)

    report_lines = []
    total_missing = 0
    total_covered = 0

    # 按字典汇总缺失（因为一个字典可能对应多张表/多字段）
    # key: dict_name, value: set of missing original texts
    dict_missing: dict[str, set[str]] = defaultdict(set)

    for class_name, fields_map in mapping["tables"].items():
        table_key = get_table_name(class_name, md_keys)
        if table_key is None:
            report_lines.append(f"[跳过] {class_name}: 在 MasterData 中找不到对应表")
            continue

        # 收集该表所有字段的原文（按字段分组，因为同一字典不同字段都要查）
        for field_name, spec in fields_map.items():
            rules = spec if isinstance(spec, list) else [spec]
            dict_names = [r["dict"] for r in rules]

            # 该字段的所有原文
            field_texts = collect_field_texts(md, table_key, [field_name])
            if not field_texts:
                continue

            # 预加载 fallback 链的所有字典
            dicts_loaded = {dn: load_translations(trans_dir, dn) for dn in dict_names}

            field_missing = set()
            for text in field_texts:
                # fallback：只要在链里任一字典有翻译，就算覆盖
                covered = any(text in dicts_loaded[dn] for dn in dict_names)
                if not covered:
                    field_missing.add(text)
                else:
                    total_covered += 1

            # 缺失项归类：归入 fallback 链的第一个字典（与运行时优先级一致）
            # 因为现在 names 只给角色名（MCharacters/MTavernDialogue），不再当通用 fallback，
            # 各表的缺失自然落到各自的表专属字典
            if dict_names:
                dict_missing[dict_names[0]] |= field_missing

    # 4. 导出按字典分组的待翻译文件
    for dn in sorted(dict_missing):
        missing_set = dict_missing[dn]
        if not missing_set:
            continue

        out_path = out_dir / dn / "zh_Hans.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # 留空译文
        empty = {k: "" for k in sorted(missing_set)}
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(empty, f, ensure_ascii=False, indent=4)

        total_missing += len(missing_set)
        report_lines.append(f"{dn}: 缺失 {len(missing_set)} 条")

    # 5. 汇总报告
    report_lines.append("")
    report_lines.append(f"=== 汇总 ===")
    report_lines.append(f"已覆盖: {total_covered} 条")
    report_lines.append(f"待翻译: {total_missing} 条")

    summary_path = out_dir / "_summary.txt"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(report_lines))

    # 控制台输出
    for line in report_lines:
        print(line)
    print(f"\n待翻译文件已导出到: {out_dir}")


if __name__ == "__main__":
    main()
