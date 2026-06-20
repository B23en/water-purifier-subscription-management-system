import pandas as pd
from pathlib import Path


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


def load_channel_map(file_path: Path):
    df = read_csv_auto(file_path)
    df = normalize_columns(df).fillna("")

    cols = list(df.columns)

    sales_col = next((c for c in cols if str(c).strip() in ["판매 채널", "판매채널"]), None)
    billto_col = next((c for c in cols if str(c).strip() == "BILLTO"), None)

    code_cols = [c for c in cols if str(c).startswith("채널분류코드")]
    name_cols = [c for c in cols if str(c).startswith("채널분류") and "코드" not in str(c)]

    if not code_cols or not name_cols:
        raise ValueError(f"채널분류코드/채널분류 컬럼을 찾지 못했습니다. 현재 컬럼: {cols}")

    sales_code_col = code_cols[0]
    sales_name_col = name_cols[0]

    billto_code_col = code_cols[1] if len(code_cols) > 1 else code_cols[0]
    billto_name_col = name_cols[1] if len(name_cols) > 1 else name_cols[0]

    sales_map = {}
    billto_map = {}

    if sales_col:
        temp = df[[sales_col, sales_code_col, sales_name_col]].copy()
        temp.columns = ["key", "code", "name"]

        for _, r in temp.iterrows():
            key = clean(r["key"])
            if key and key not in sales_map:
                sales_map[key] = (clean(r["code"]), clean(r["name"]))

    if billto_col:
        temp = df[[billto_col, billto_code_col, billto_name_col]].copy()
        temp.columns = ["key", "code", "name"]

        for _, r in temp.iterrows():
            key = clean(r["key"])
            if key and key not in billto_map:
                billto_map[key] = (clean(r["code"]), clean(r["name"]))

    return sales_map, billto_map


def apply_channel(df, sales_map, billto_map):
    df = df.copy()

    def get_channel(row):
        billto = clean(row.get("BILLTO", ""))
        sales = clean(row.get("판매채널", ""))

        # 우선순위: BILLTO > 판매채널
        if billto in billto_map:
            return billto_map[billto]
        if sales in sales_map:
            return sales_map[sales]

        return ("B2B외", "B2B외")

    result = df.apply(get_channel, axis=1)

    df["채널분류코드"] = [r[0] for r in result]
    df["채널분류"] = [r[1] for r in result]

    return df
