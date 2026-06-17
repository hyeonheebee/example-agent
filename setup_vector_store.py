import dotenv
dotenv.load_dotenv()

from openai import OpenAI

client = OpenAI()

vector_store = client.vector_stores.create(
    name="Life Coach Goals"
)
print(f"Vector Store 생성 완료!")
print(f"VECTOR_STORE_ID= '{vector_store.id}'")

with open("my_goals.txt", "rb") as f:
    client.vector_stores.files.upload_and_poll(
        vector_store_id=vector_store.id,
        file=f,
    )
print("파일업로드 완료!")
print(f"\n이 ID를 복사해둬: {vector_store.id}")