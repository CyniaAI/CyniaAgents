# Developing Components

A component is a Python module placed inside the `components/` directory.  Each component must expose a `get_component()` function returning an object derived from `BaseComponent`.

```python
from component_base import BaseComponent

class MyComponent(BaseComponent):
    name = "My Generator"
    description = "Does something amazing"

    def render(self):
        import streamlit as st
        st.write("Hello from my component")
```

Create a file such as `components/my_component.py` containing the class above and a `get_component()` function:

```python
def get_component():
    return MyComponent()
```

After restarting the UI you can enable the component from the **Component Center** page in the sidebar. Once enabled it appears as its own page. Any libraries required by your component should be installed in the Python environment running the UI.

## Adding Configuration Items

Components can expose custom configuration values which are stored in the project's `.env` file. Use `config.register_config_item()` to define a new key, description and input type:

```python
import config

config.register_config_item(
    "MY_SETTING",
    "Description of my setting",
    default="some_default",
    input_type="text"  # other options: "password" or "select"
)
```

Registered items appear in the **Configuration Center** page where their values can be edited through the UI.
When using ``input_type='select'`` pass an ``options`` list to define the dropdown choices.

## Interacting with the LLM

Use the :class:`LLM` helper from ``utils`` for any language model requests:

```python
from utils import LLM

llm = LLM()
response = llm.ask("You are a helpful assistant.", "Hello")
```

For multi-turn interactions create a conversation instance and call ``send()``:

```python
conv = llm.create_conversation("You are a helpful assistant.")
response = conv.send("Hello")
```
The object keeps track of the full history in ``conv.history``.
You may override provider settings when instantiating the helper:

```python
llm = LLM(provider="openai", model_name="gpt-4")
```
Missing parameters fall back to values defined in `config.py`.

