import os
import json
import re
import openai
from supabase import create_client, Client

# 1. 載入必要參數 (建議放在環境變數)
openai.api_key = os.getenv("OPENAI_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# 建立正規表示式，偵測是否為 mm-dd-yyyy 格式
date_pattern = re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$")


def main():
    # 2. 讀取本地 pages.json
    with open("pages.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    # 假設結構為 { "result": [ [uid, page_title], [uid, page_title], ... ] }
    all_pages = data.get("result", [])

    # 3. 過濾 UID 是日期格式的頁面
    filtered_pages = [(uid, title) for (uid, title) in all_pages if not date_pattern.match(uid)]

    # 4. 建立 supabase 連線
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 要寫入的資料表名稱
    table_name = "pages"

    # 5. 依序呼叫 OpenAI Embedding API 並使用 upsert 寫入資料庫
    for uid, page_title in filtered_pages:
        # 呼叫 OpenAI Embedding API
        response = openai.embeddings.create(model="text-embedding-3-small", input=page_title)
        # 從回應中取出 embedding (向量)
        embedding = response.data[0].embedding

        # 準備要 upsert 的資料
        row_data = {"uid": uid, "title": page_title, "embedding": embedding}

        # 執行 upsert
        #   - on_conflict="uid"：表示若 uid 已存在則更新，否則插入新資料
        #   - 在 Supabase 資料表裡，uid 必須是 PRIMARY KEY 或 UNIQUE
        try:
            result = supabase.table(table_name).upsert(row_data, on_conflict="uid").execute()
            if result.model_dump().get("error"):
                print(f"寫入失敗：{result['error']}")
            else:
                print(f"成功 upsert 資料：UID={uid}, Title={page_title}")
        except Exception as e:
            print(f"寫入過程發生錯誤：{e}")


if __name__ == "__main__":
    main()
