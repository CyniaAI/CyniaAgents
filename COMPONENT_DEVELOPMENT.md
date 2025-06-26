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

Components can expose custom configuration values which are stored in the project's `.env` file. Use `config.register_config_item()` to define a new key and description:

```python
import config

config.register_config_item(
    "MY_SETTING",
    "Description of my setting",
    default="some_default"
)
```

Registered items appear in the **Configuration Center** page where their values can be edited through the UI.
