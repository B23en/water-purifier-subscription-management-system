import os
import pandas as pd

# ✅ 경로 설정
base_path = r"V:\한국 정수기 계정\SummaryDB"

# ✅ csv 파일 목록
csv_files = [f for f in os.listdir(base_path) if f.endswith(".csv")]

print(f"총 {len(csv_files)}개 파일 발견")

for file in csv_files:
    try:
        csv_path = os.path.join(base_path, file)
        parquet_path = os.path.join(base_path, file.replace(".csv", ".parquet"))

        print(f"변환 중: {file}")

        # ✅ CSV 읽기 (한글 깨짐 대응)
        df = pd.read_csv(csv_path, encoding="utf-8-sig")

        # ✅ Parquet 저장 (압축 포함)
        df.to_parquet(parquet_path, engine="pyarrow", compression="snappy", index=False)

        print(f"완료 → {parquet_path}")

    except Exception as e:
        print(f"에러 발생: {file} / {e}")