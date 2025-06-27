from component_base import BaseComponent
import streamlit as st
import utils
import artifact_manager
import tempfile
import os

artifact_manager.register_artifact_type("text")


class ExampleComponent(BaseComponent):
    name = "Echo Agent"
    description = "Demo agent that sends your prompt to the LLM and displays the response."
    requirements: list[str] = []

    def __init__(self):
        super().__init__()
        self.llm = utils.LLM()
        if "example_conv" not in st.session_state:
            st.session_state.example_conv = self.llm.create_conversation(
                "You are a helpful assistant."
            )

    def render(self):
        st.header(self.name)
        prompt = st.text_area("Prompt")
        if st.button("Send"):
            with st.spinner("Generating..."):
                reply = st.session_state.example_conv.send(prompt)
        history_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in st.session_state.example_conv.history[1:]
        )
        st.text_area("Conversation", value=history_text, height=300)

        if st.button("Save Conversation Artifact"):
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
                f.write(history_text)
                temp_path = f.name
            artifact_manager.write_artifact(
                self.name,
                temp_path,
                "Conversation log",
                "text",
            )
            os.remove(temp_path)
            st.success("Artifact saved")

def get_component():
    return ExampleComponent()
