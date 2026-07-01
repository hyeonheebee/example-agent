from google.adk.agents import Agent, SequentialAgent
from google.adk.tools.tool_context import ToolContext
from google import genai
from dotenv import load_dotenv

load_dotenv()


def save_story(pages: list[dict], tool_context: ToolContext) -> str:
    tool_context.state["pages"] = pages
    return f"{len(pages)}페이지 저장 완료!"


async def generate_image(tool_context: ToolContext) -> str:
    import google.genai.types as types
    from openai import OpenAI
    import base64


    pages = tool_context.state.get("pages", [])

    openai_client = OpenAI()

    for i, page in enumerate(pages):
        response = openai_client.images.generate(
            model="gpt-image-1",
            prompt=page["visual"],
            size="1024x1024",
            n=1,
        )
        image_bytes = base64.b64decode(response.data[0].b64_json)

        artifact = types.Part.from_bytes(data=image_bytes, mime_type="image/png")
        await tool_context.save_artifact(f"page_{i+1}.png", artifact)

    return f"{len(pages)}개 페이지 이미지 생성 완료!"

story_writer = Agent(
    name="story_writer",
    model="openai/gpt-4o-mini",
    instruction="""사용자가 테마를 주면 5페이지짜리 어린이 동화를 써줘. 반드시 save_story 툴을 호출해서 결과를 저장해. 
    pages는 다음 형태의 리스트야: [{"page": 1, "text": "동화 내용", "visual": "이미지 설명(영어로)"}]
    visual은 이미지 생성 프롬프트니까 영어로 써줘.""",
    tools=[save_story],
)

illustrator = Agent(
    name="illustrator",
    model="openai/gpt-4o-mini",
    instruction="""generate_image 툴을 호출해서 각 페이지 이미지를 생성해줘. 툴 호출 후 몇 개 생성됐는지 알려줘..""",
    tools=[generate_image],
)

root_agent = SequentialAgent(
    name="storybook_creator",
    description="어린이 동화 생성 에이전트",
    sub_agents=[story_writer, illustrator],
)