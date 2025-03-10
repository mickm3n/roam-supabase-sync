import os
import json
import re
import requests
import openai
from supabase import create_client, Client

# 1. 載入必要參數 (建議放在環境變數)
openai.api_key = os.getenv("OPENAI_API_KEY")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Roam Research API 參數
ROAM_API_BASE_URL = os.getenv("ROAM_API_BASE_URL")
ROAM_API_GRAPH = os.getenv("ROAM_API_GRAPH")
ROAM_API_KEY = os.getenv("ROAM_API_KEY")

# 建立正規表示式，偵測是否為 mm-dd-yyyy 格式
date_pattern = re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$")


def main():
    # 2. 從 Roam Research API 取得所有頁面資料
    url = f"{ROAM_API_BASE_URL}/api/graph/{ROAM_API_GRAPH}/q"
    headers = {
        "Content-Type": "application/json",
        "X-Authorization": f"Bearer {ROAM_API_KEY}",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "User-Agent": "PostmanRuntime/7.43.0",
    }
    payload = {
        "query": (
            "[:find ?uid ?page-title " ":where [?id :node/title ?page-title][?id :block/uid ?uid]]"
        ),
        "args": [],
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code != 200:
        print(f"API 呼叫失敗：{response.status_code} - {response.text}")
        return
    data = response.json()
    # 假設結構為 { "result": [ [uid, page_title], [uid, page_title], ... ] }
    all_pages = data.get("result", [])
    # 可選：將結果儲存到 pages.json 作為備份
    with open("pages.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

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
