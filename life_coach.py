import dotenv
dotenv.load_dotenv()

import asyncio
import base64
import copy
import streamlit as st
from openai import OpenAI
from agents import Agent, Runner, SQLiteSession, WebSearchTool, FileSearchTool, ImageGenerationTool

class FilteredSQLiteSession(SQLiteSession):
    def _Remove_action_Recursive(self, obj):
        if isinstance(obj, dict):
            cleaned = {k: v for k , v in obj.items() if k != "action" }
            return {k: self._Remove_action_Recursive(v) for k, v in cleaned.items()}
        elif isinstance(obj, list):
            return [self._Remove_action_Recursive(item) for item in obj]
        else:
            return obj
    async def add_items(self, items):
        cleaned = [self._Remove_action_Recursive(copy.deepcopy(item)) for item in items]
        await super().add_items(cleaned)

    async def get_items(self):
        items = await super().get_items()
        return [
            self._Remove_action_Recursive(copy.deepcopy(item)) for item in items
        ]
client = OpenAI()

VECTOR_STORE_ID = "vs_6a32b672d8e48191b2dc1a0d55524725"
st.set_page_config(page_title="Life Coach", page_icon="🫶")
st.title("🫶Life Coach")
st.caption("목표달성, 습관형성, 자기개발을 돕는 AI코치")

if "agent" not in st.session_state:
    st.session_state["agent"] = Agent(
        name="Life Coach", 
        instructions="""You are an encouraging and supportive life coach. Help users achieve their goals, build positive habits, 
  and grow personally.
  You have access to the following tools:
    - Web Search Tool: Use this when the user asks about current events or general tips you don't know. Always search 
  before answering.
    - File Search Tool: Use this when the user asks about their personal goals, progress, or anything related to their own 
  files. Always search the files before answering personal questions.

    - Image Generation Tool: Use this to create vision boards, motivational posters, or visual celebrations. Use it when:
      IMPORTANT: Always write a warm encouraging message in Korean FIRST, then generate the image.
    Use it when:
        * The user achieves a goal → first congratulate them in text, then create a celebration image
        * The user asks for a vision board → first confirm their goals, then create the image
        * The user wants a motivational poster → first describe what you'll create, then generate it
        * Visual encouragement would help

  Always be warm, uplifting, and solution-focused. Always respond in Korean.
  Always use the Tools to find up-to-date information before answering.""",
        tools=[WebSearchTool(),
               FileSearchTool(
                   vector_store_ids=[VECTOR_STORE_ID],
                   max_num_results=3
               ),
               ImageGenerationTool(
                   tool_config={
                       "type": "image_generation",
                       "quality": "medium",
                       "output_format": "jpeg",
                       "partial_images": 1,
                   }
               )
               ],
    )
agent = st.session_state["agent"]

session = FilteredSQLiteSession("Life-coach", "Life-coach-memory.db")


async def paint_history():
    messages = await session.get_items()

    for message in messages: 
        if "role" in message:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.write(message["content"])
                else:
                    if message["type"] == "message":
                        st.write(message["content"][0]["text"])
        if "type" in message:
            message_type = message["type"]
            
            if message_type == "web_search_call":
                with st.chat_message("ai"):
                    query = message.get("query", "")
                    if query:
                        st.write(f"웹 검색 중...'{query}'") 
            elif message_type == "file_search_call":
                with st.chat_message("ai"):
                    query = message.get("query", "")
                    if query:
                        st.write(f"파일 검색 중...'{query}'") 
            elif message_type == "image_generation_call":
                with st.chat_message("ai"):
                    image = base64.b64decode(message["result"])
                    st.image(image)
asyncio.run(paint_history())

def update_status(status_container, event):
    status_messages = {
        "response.web_search_call.in_progress": ("웹 검색 시작...", "running"),
        "response.web_search_call.searching": ("웹 검색중..", "running"),
        "response.web_search_call.completed": ("웹 검색 완료!", "complete"),
        "response.file_search_call.in_progress": ("파일 검색 시작...", "running"),
        "response.file_search_call.searching": ("파일 검색중..", "running"),
        "response.file_search_call.completed": ("파일 검색 완료!", "complete"),
        "response.image_generation_call.in_progress": ("🎨 이미지 그리는 중...", "running"),
        "response.image_generation_call.generating": ("🎨 이미지 생성 중...", "running"),
        "response.completed": ("끝!", "complete"),


    }
    if event in status_messages:
        label, state = status_messages[event]
        status_container.update(label=label, state=state)


async def run_agent(message):
    with st.chat_message("ai"):
        status_container = st.status("wating...", expanded=False)
        text_placeholder = st.empty()
        image_placeholder = st.empty()

        response = ""

        stream = Runner.run_streamed(agent, message, session=session)

        async for event in stream.stream_events():

            if event.type == "raw_response_event":
                update_status(status_container, event.data.type)
                if event.data.type == "response.output_text.delta":
                    response += event.data.delta
                    text_placeholder.write(response) 
                elif event.data.type == "response.image_generation_call.partial_image":
                    image = base64.b64decode(event.data.partial_image_b64)
                    image_placeholder.image(image)
        
prompt = st.chat_input("목표나 고민을 말해보세요")

if prompt:
    with st.chat_message("human"):
        st.write(prompt)
    asyncio.run(run_agent(prompt))

with st.sidebar:
    if st.button("대화 초기화"):
        asyncio.run(session.clear_session())