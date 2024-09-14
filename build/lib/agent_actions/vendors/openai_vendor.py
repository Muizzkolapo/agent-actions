import os
from langchain.chains import create_structured_output_runnable
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from agent_actions.core.utils import extract_objects

class OpenAIHandler:
    @staticmethod
    def invoke(agent_config, prompt_config, input_documentation, schema):
        model_name = agent_config['model_name']
        api_key = os.getenv(agent_config['api_key'])

        llm = ChatOpenAI(model=model_name, temperature=0, api_key=api_key)
        prompt = ChatPromptTemplate.from_messages(prompt_config)
        agent = create_structured_output_runnable(schema, llm, prompt)
        response = agent.invoke({"input": input_documentation, "chat_history": []})
        #--this would help extract list fromt the key as openai is in key:[] format
        transformed_response = extract_objects(response)
        return transformed_response
