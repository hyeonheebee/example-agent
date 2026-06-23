import dotenv
dotenv.load_dotenv()

import asyncio
import streamlit as st
from pydantic import BaseModel
from agents import (
    Agent, Runner, SQLiteSession, handoff
)
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from agents.extensions import handoff_filters

class HandoffData(BaseModel):
    to_agent_name: str
    reason: str

menu_agent = Agent(
    name="Menu Agent",
    instructions=f"""
    당신은 레스토랑의 메뉴 전문가입니다. 다음을 도와드릴 수 있습니다. :
    - 메뉴 항목 및 설명
    - 메뉴의 재료 및 알레르기 정보 
    - 채식, 비건, 글루텐프리 등 식이습관을 고려한 메뉴옵션
    - 음식 추천
    항상 한국어로 친절하게 답변하세요. 메뉴 외의 질문(주문, 예약)이 오면 해당 전문가에게 연결하세요""",
)

order_agent = Agent(
    name="Order Agent",
    instructions=f"""
    당신은 레스토랑의 주문 전문가입니다. 다음을 도와드릴 수 있습니다. :
    - 음식 주문 받기
    - 주문 내역 확인 및 수정
    - 조리 예상 시간 안내
    - 메뉴를 정확하게 확인
    주문을 받을때는 메뉴의 항목과 수량을 명확하게 항상 확인하세요. 
    항상 한국어로 친절하게 답변하세요. 주문 외의 질문(메뉴, 예약)이 오면 해당 전문가에게 연결하세요 """,
)

reservation_agent = Agent(
    name="Reservation Agent",
    instructions=f"""
    당신은 레스토랑의 예약 전문가입니다. 다음을 도와드릴 수 있습니다. :
    - 테이블 예약
    - 예약 가능 여부 확인
    - 예약 변경 및 취소
    - 예약 확인번호 제공
    예약시 반드시 다음을 확인하세요 : 인원수, 날짜, 시간, 이름. 
    항상 한국어로 친절하게 답변하세요.예약 외의 질문(주문, 메뉴)이 오면 해당 전문가에게 연결하세요 """,
)

def handle_handoff(wrapper, input_data: HandoffData):
    with st.sidebar:
        st.write(f"🔄 **{input_data.to_agent_name}** 으로 연결중 입니다. 잠시만 기다려주세요....")
        st.caption(f"이유: {input_data.reason}")

def make_handoff(agent):
    return handoff(
        agent=agent,
        on_handoff=handle_handoff,
        input_type=HandoffData,
        input_filter=handoff_filters.remove_all_tools,
    )

triage_agent = Agent(
    name="Triage Agent",
    instructions=f"""{RECOMMENDED_PROMPT_PREFIX}
    당신은 레스토랑의 고객문의의 첫번째 안내 담당입니다.
    고객의 요청을 파악해서 적합한 에이전트 전문가에게 연결하세요:
    - 메뉴, 재료, 알레르기 관련 질문은 Menu Agent 전문가에게 연결
    - 음식 주문 관련 질문은 Order Agent 전문가에게 연결
    - 테이블 예약 등 예약 관련 질문은 Reservation Agent 전문가에게 연결
    연결할때는 "ooo 전문가(Agent라는 표현은 제외하고) 에게 연결해드릴게요! 잠시만 기다려주세요" 라고 안내하세요.
    항상 한국어로 친절하게 답변하세요.""",
    handoffs=[
        make_handoff(menu_agent),
        make_handoff(order_agent),
        make_handoff(reservation_agent),
    ],
)
menu_agent.handoffs = [make_handoff(order_agent), make_handoff(reservation_agent)]
order_agent.handoffs = [make_handoff(menu_agent), make_handoff(reservation_agent)]
reservation_agent.handoffs = [make_handoff(order_agent), make_handoff(menu_agent)]

st.set_page_config(page_title="레스토랑 봇", page_icon="🍽️")
st.title("🍽️ Hyeonheebee's Restaurant Bot ")
st.caption("메뉴, 주문, 예약까지 전부 도와드려요!")

if "agent" not in st.session_state:
    st.session_state["agent"] = triage_agent
session = SQLiteSession("restaurant-bot", "restaurant-bot-memory.db")

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
asyncio.run(paint_history())

async def run_agent(message):
    with st.chat_message("ai"):
        text_placeholder = st.empty()
        response = ""

        stream = Runner.run_streamed(
            st.session_state["agent"],
            message,
            session=session,
        )

        async for event in stream.stream_events():
            if event.type == "raw_response_event":
                if event.data.type == "response.output_text.delta":
                    response += event.data.delta
                    text_placeholder.write(response)

            elif event.type == "agent_updated_stream_event": 
                if st.session_state["agent"].name != event.new_agent.name:
                    st.write(f"🤖 **{event.new_agent.name} 으로 연결됩니다..잠시만 기다려주세요.")
                    st.session_state["agent"] = event.new_agent
                    text_placeholder = st.empty()
                    st.session_state["text_placeholder"] = text_placeholder
                    response = ""

prompt = st.chat_input("메뉴, 주문, 예약 중 무엇을 도와드릴까요?")

if prompt:
    with st.chat_message("human"):
        st.write(prompt)
    asyncio.run(run_agent(prompt))
with st.sidebar:
    st.subheader("🔄 Agent 활동 확인하기")
    if st.button("대화 초기화하기"):
        asyncio.run(session.clear_session())
        st.session_state["agent"] = triage_agent
