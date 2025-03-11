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

    # 5. 取得目前資料庫中的所有資料 (使用分頁取得所有資料)
    page_size = 1000  # Supabase 每頁最大資料量
    from_range = 0
    all_data = []
    
    while True:
        db_result = supabase.table(table_name).select("uid, title").range(from_range, from_range + page_size - 1).execute()
        if db_result.model_dump().get("error"):
            print(f"取得資料庫資料失敗：{db_result.model_dump().get('error')}")
            return
        
        # 收集當前頁面的資料
        if db_result.data:
            all_data.extend(db_result.data)
            # 如果返回的資料筆數少於 page_size，表示已經取得所有資料
            if len(db_result.data) < page_size:
                break
            # 否則更新範圍，繼續獲取下一頁資料
            from_range += page_size
        else:
            # 沒有更多資料
            break
    
    print(f"從資料庫取得總計 {len(all_data)} 筆資料")

    # 將現有資料轉換為字典，方便比對
    existing_pages = {item["uid"]: item["title"] for item in all_data}
    with open("supabase.json", "w", encoding="utf-8") as f:
        json.dump(existing_pages, f, ensure_ascii=False, indent=4)

    # 6. 計算要新增、更新和刪除的項目
    roam_page_dict = {uid: title for uid, title in filtered_pages}
    with open("roamresearch.json", "w", encoding="utf-8") as f:
        json.dump(roam_page_dict, f, ensure_ascii=False, indent=4)

    # 需要新增或更新的項目
    to_upsert = []
    for uid, title in filtered_pages:
        # 如果 UID 不存在或標題已變更，則需要更新
        if uid not in existing_pages or existing_pages[uid] != title:
            to_upsert.append((uid, title))

    # 需要刪除的項目（在資料庫中但不在 Roam 中的項目）
    to_delete = [uid for uid in existing_pages if uid not in roam_page_dict]

    # 7. 處理新增和更新項目
    print(f"需要新增或更新的項目數：{len(to_upsert)}")
    for uid, page_title in to_upsert:
        # 呼叫 OpenAI Embedding API
        response = openai.embeddings.create(model="text-embedding-3-small", input=page_title)
        # 從回應中取出 embedding (向量)
        embedding = response.data[0].embedding

        # 準備要 upsert 的資料
        row_data = {"uid": uid, "title": page_title, "embedding": embedding}

        # 執行 upsert
        try:
            result = supabase.table(table_name).upsert(row_data, on_conflict="uid").execute()
            if result.model_dump().get("error"):
                print(f"寫入失敗：{result['error']}")
            else:
                action = "更新" if uid in existing_pages else "新增"
                print(f"成功{action}資料：UID={uid}, Title={page_title}")
        except Exception as e:
            print(f"寫入過程發生錯誤：{e}")

    # 8. 處理需要刪除的項目
    print(f"需要刪除的項目數：{len(to_delete)}")
    for uid in to_delete:
        try:
            result = supabase.table(table_name).delete().eq("uid", uid).execute()
            if result.model_dump().get("error"):
                print(f"刪除失敗：{result['error']}")
            else:
                print(f"成功刪除資料：UID={uid}, Title={existing_pages[uid]}")
        except Exception as e:
            print(f"刪除過程發生錯誤：{e}")


if __name__ == "__main__":
    main()
