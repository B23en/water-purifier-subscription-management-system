import pandas as pd
from pathlib import Path


STANDARD_COLS = ["모델", "Tool", "모델명", "기능"]


def read_csv_auto(path: Path):
    encodings = ["utf-16", "utf-16le", "utf-16be", "utf-8-sig", "cp949", "euc-kr", "utf-8"]
    seps = [",", "\t", "|", ";"]

    last_error = None
    for enc in encodings:
        for sep in seps:
            try:
                df = pd.read_csv(path, dtype=str, encoding=enc, sep=sep)
                df = df.fillna("")

                if len(df.columns) == 1:
                    continue

                return df
            except Exception as e:
                last_error = e

    raise ValueError(f"CSV 읽기 실패: {path}\n마지막 오류: {last_error}")


def normalize_columns(df):
    df = df.copy()
    df.columns = [str(c).strip().replace("\n", "").replace("\r", "") for c in df.columns]
    return df


def clean(x):
    if pd.isna(x):
        return ""
    return str(x).strip()


def normalize_model_key(x):
    return clean(x).upper()


def ensure_model_file(file_path: Path):
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if not file_path.exists():
        empty_df = pd.DataFrame(columns=STANDARD_COLS)
        empty_df.to_csv(file_path, index=False, encoding="utf-8-sig")

    df = read_csv_auto(file_path)
    df = normalize_columns(df).fillna("")

    cols = list(df.columns)

    model_col = next((c for c in cols if str(c).strip() == "모델"), None)
    tool_col = next((c for c in cols if str(c).strip() in ["Tool", "Tool 그룹"]), None)
    model_name_col = next((c for c in cols if str(c).strip() in ["모델명", "Tool 구분"]), None)
    func_col = next((c for c in cols if str(c).strip() in ["기능", "기능구분", "기능 구분"]), None)

    if model_col and tool_col and model_name_col and func_col:
        temp = df[[model_col, tool_col, model_name_col, func_col]].copy()
        temp.columns = STANDARD_COLS
        temp.to_csv(file_path, index=False, encoding="utf-8-sig")
        return

    for col in STANDARD_COLS:
        if col not in df.columns:
            df[col] = ""

    df = df[STANDARD_COLS + [c for c in df.columns if c not in STANDARD_COLS]]
    df.to_csv(file_path, index=False, encoding="utf-8-sig")


def load_model_map(file_path: Path):
    ensure_model_file(file_path)

    df = read_csv_auto(file_path)
    df = normalize_columns(df).fillna("")

    cols = list(df.columns)

    model_col = next((c for c in cols if str(c).strip() == "모델"), None)
    tool_col = next((c for c in cols if str(c).strip() in ["Tool", "Tool 그룹"]), None)
    model_name_col = next((c for c in cols if str(c).strip() in ["모델명", "Tool 구분"]), None)
    func_col = next((c for c in cols if str(c).strip() in ["기능", "기능구분", "기능 구분"]), None)

    if not model_col or not tool_col or not model_name_col or not func_col:
        raise ValueError(f"❌ 모델 매핑 컬럼 찾기 실패\n현재 컬럼: {cols}")

    temp = df[[model_col, tool_col, model_name_col, func_col]].copy()
    temp.columns = STANDARD_COLS

    model_map = {}

    for _, r in temp.iterrows():
        key = normalize_model_key(r["모델"])
        if key and key not in model_map:
            model_map[key] = (
                clean(r["Tool"]),
                clean(r["모델명"]),
                clean(r["기능"]),
            )

    return model_map


def apply_model(df, model_map):
    df = df.copy()

    if "모델" not in df.columns:
        df["Tool"] = ""
        df["모델명"] = ""
        df["기능"] = ""
        return df

    def get_model(model):
        return model_map.get(normalize_model_key(model), ("", "", ""))

    result = df["모델"].map(get_model)

    df["Tool"] = [r[0] for r in result]
    df["모델명"] = [r[1] for r in result]
    df["기능"] = [r[2] for r in result]

    return df


def get_unknown_models(df, model_map):
    if "모델" not in df.columns:
        return []

    unknown = []
    seen = set()

    for value in df["모델"].astype(str).fillna("").tolist():
        raw = clean(value)
        key = normalize_model_key(raw)

        if not raw:
            continue

        if key not in model_map and key not in seen:
            unknown.append(raw)
            seen.add(key)

    return unknown


def update_model_category(model_file: Path, new_rows):
    """
    new_rows 예시:
    [
        {"모델":"WD123ABC", "Tool":"정수기", "모델명":"오브제 정수기", "기능":"냉온정"},
        ...
    ]
    """
    ensure_model_file(model_file)

    df = read_csv_auto(model_file)
    df = normalize_columns(df).fillna("")

    # 표준화
    cols = list(df.columns)
    model_col = next((c for c in cols if str(c).strip() == "모델"), None)
    tool_col = next((c for c in cols if str(c).strip() in ["Tool", "Tool 그룹"]), None)
    model_name_col = next((c for c in cols if str(c).strip() in ["모델명", "Tool 구분"]), None)
    func_col = next((c for c in cols if str(c).strip() in ["기능", "기능구분", "기능 구분"]), None)

    if model_col and tool_col and model_name_col and func_col:
        df = df[[model_col, tool_col, model_name_col, func_col]].copy()
        df.columns = STANDARD_COLS
    else:
        for col in STANDARD_COLS:
            if col not in df.columns:
                df[col] = ""
        df = df[STANDARD_COLS]

    add_df = pd.DataFrame(new_rows)
    for col in STANDARD_COLS:
        if col not in add_df.columns:
            add_df[col] = ""

    add_df = add_df[STANDARD_COLS].copy()

    # key 기준 기존 덮어쓰기
    df["_key"] = df["모델"].map(normalize_model_key)
    add_df["_key"] = add_df["모델"].map(normalize_model_key)

    base_keys = set(df["_key"].tolist())

    for _, row in add_df.iterrows():
        key = row["_key"]
        if not key:
            continue

        if key in base_keys:
            idx = df.index[df["_key"] == key][0]
            df.at[idx, "모델"] = clean(row["모델"])
            df.at[idx, "Tool"] = clean(row["Tool"])
            df.at[idx, "모델명"] = clean(row["모델명"])
            df.at[idx, "기능"] = clean(row["기능"])
        else:
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            base_keys.add(key)

    df = df.drop(columns=["_key"], errors="ignore")
    df = df.drop_duplicates(subset=["모델"], keep="last")
    df.to_csv(model_file, index=False, encoding="utf-8-sig")