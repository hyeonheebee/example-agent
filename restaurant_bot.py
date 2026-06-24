import dotenv
dotenv.load_dotenv()

import asyncio
import streamlit as st
from pydantic import BaseModel
from agents import (
    Agent, Runner, SQLiteSession, handoff,
    input_guardrail, output_guardrail,
    GuardrailFunctionOutput,
    RunContextWrapper, TResponseInputItem,
    InputGuardrailTripwireTriggered, 
    OutputGuardrailTripwireTriggered,
)
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
from agents.extensions import handoff_filters

class InputGuardrailOutput(BaseModel):
    is_off_topic: bool
    has_bad_language: bool
    reason: str

input_guardrail_agent = Agent(
    name="Input Guardrail Agent",
    instructions="""사용자의 메시지를 분석해서 두 가지를 판단하세요. 
    
    is_off_topic: 레스토랑과 완전 무관한 주제라면 True
    (레스토랑 관련 : 메뉴, 음식, 주문, 예약, 불만, 서비스, 음료, 가격 등)
    (무관한 주제 예시 : 정치, 코딩, 날씨, 주식, 연예)
    짧은 대화("네", "아니요", "감사해요", "다시 주문할게요" 등)는 False

    has_bad_language: 욕설, 혐오, 표현, 폭력적 언어가 있으면 True
    레스토랑 관련 정상 메시지면 둘다 False 로 반환하세요. """,

    output_type=InputGuardrailOutput,
)

@input_guardrail
async def restaurant_input_guardrail(
    ctx: RunContextWrapper,
    agent: Agent,
    input: str | list[TResponseInputItem]
) -> GuardrailFunctionOutput:
    result = await Runner.run(input_guardrail_agent, input, context=ctx.context)
    output = result.final_output_as(InputGuardrailOutput)

    triggered = output.is_off_topic or output.has_bad_language

    return GuardrailFunctionOutput(
        output_info=output,
        tripwire_triggered=triggered,
    )

class OutputGuardrailOutput(BaseModel):
    is_unprofessional: bool
    has_internal_info: bool
    reason: str

output_guardrail_agent = Agent(
    name="Output Guardrail Agent",
    instructions="""레스토랑 봇의 응답을 분석해서 두 가지를 판단하세요.
    
    is_unprofessional: 무례하거나 비 전문적인 표현이 있으면 True (욕설, 고객비하, 경멸적 표현 등)
    
    has_internal_info: 공개하면 안되는 내부 정보가 있으면 True(원가, 마진, 직원 개인정보, 고객 정보, 공급업체 정보 등)
    
    정상적인 레스토랑 안내 응답이면 둘다 False 로 반환하세요.""",
    output_type=OutputGuardrailOutput,
)

@output_guardrail
async def restaurant_output_guardrail(
    ctx: RunContextWrapper,
    agnet: Agent,
    output: str
) -> GuardrailFunctionOutput:
    
    result = await Runner.run(output_guardrail_agent, output, context=ctx.context)
    validation = result.final_output_as(OutputGuardrailOutput)

    triggered = validation.is_unprofessional or validation.has_internal_info

    return GuardrailFunctionOutput(
        output_info=validation,
        tripwire_triggered=triggered,
    )


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
    항상 한국어로 친절하게 답변하세요. 메뉴 외의 질문(주문, 예약)이 명시적으로 오면 해당 전문가에게 연결하세요""",
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
    항상 한국어로 친절하게 답변하세요. 주문 외의 질문(메뉴, 예약)이 명시적으로 오면 해당 전문가에게 연결하세요 """,
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
    항상 한국어로 친절하게 답변하세요.예약 외의 질문(주문, 메뉴)이 명시적으로 오면 해당 전문가에게 연결하세요 """,
)

compliants_agent = Agent(
    name= "Compliants Agent",
    instructions= """당신은 레스토랑의 고객 불만 전담 상담사입니다. 
    순서대로 응대하세요:
    1. 고객 불만을 진심으로 공감하고 인정하기 ("불편하셨겠네요 정말. 죄송합니다")
    2. 상황에 맞는 해결책 제시하기 : 
    - 음식 품질 문제 => 제조리 또는 환불
    - 서비스 불만 => 할인 쿠폰 또는 매니저 콜백
    - 대기 시간 문제 => 사과 와 보상안 제공
    
    3. 심각한 문제(식중독, 안전사고)는 매니저 에스컬레이션 안내하기 
    
    절대 변명하거나 고객 감정을 무시하지 마세요. 항상 한국어로 정중하고 따뜻하고 친절하게 답변하세요. """,

    output_guardrails=[restaurant_output_guardrail],
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
    - 고객불만, 컴플레인, 환불 요청은 Compliants Agent 전문가에게 연결 
    단순 질문과 불만을 혼동하지 마세요.
    연결할때는 "ooo 전문가(Agent라는 표현은 제외하고) 에게 연결해드릴게요! 잠시만 기다려주세요" 라고 안내하세요.
    항상 한국어로 친절하게 답변하세요.""",
    handoffs=[
        make_handoff(menu_agent),
        make_handoff(order_agent),
        make_handoff(reservation_agent),
        make_handoff(compliants_agent)
    ],
    input_guardrails=[restaurant_input_guardrail],
)
menu_agent.handoffs = [make_handoff(order_agent), make_handoff(reservation_agent), make_handoff(compliants_agent)]
order_agent.handoffs = [make_handoff(menu_agent), make_handoff(reservation_agent), make_handoff(compliants_agent)]
reservation_agent.handoffs = [make_handoff(order_agent), make_handoff(menu_agent), make_handoff(compliants_agent)]
compliants_agent.handoffs = [make_handoff(order_agent), make_handoff(menu_agent), make_handoff(reservation_agent)]

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
        st.session_state["text_placeholder"] = text_placeholder
        response = ""

        try:
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
        except InputGuardrailTripwireTriggered:
            text_placeholder.warning(
                "🚫 레스토랑 관련 질문만 도와드릴 수 있어요!\n\n"
                "메뉴 문의, 주문, 예약, 불만 접수등 레스토랑에 관한 질문을 해주세요 🍽️ "
            )
        except OutputGuardrailTripwireTriggered:
            st.session_state["text_placeholder"].empty()
            text_placeholder.warning(
                "죄송합니다. 지금은 응답을 표시할 수 없습니다. 다시 질문해주세요! "
            )

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
