from component_base import BaseComponent
import streamlit as st
import utils
import config


class ExampleComponent(BaseComponent):
    name = "Echo Agent"
    description = "Demo agent that sends your prompt to the LLM and displays the response."

    def render(self):
        st.header(self.name)
        prompt = st.text_area("Prompt")
        if st.button("Generate"):
            with st.spinner("Generating..."):
                result = utils.askgpt("You are a helpful assistant.", prompt, config.GENERATION_MODEL)
            st.text_area("Result", value=result, height=300)

def get_component():
    return ExampleComponent()
