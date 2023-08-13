from typing import Optional, Any, Dict, Callable
from pydantic import BaseModel


class Message(BaseModel):
    """Pydantic model for holding LLM messages"""

    # The role of the messages author.
    # One of system, user, assistant, or function.
    role: str
    # The contents of the message. content is required for all messages,
    # and may be null for assistant messages with function calls.
    content: str
    # The name of the author of this message. name is required if role is function,
    # and it should be the name of the function whose response is in the content.
    # May contain a-z, A-Z, 0-9, and underscores, with a maximum length of 64 characters.
    name: Optional[str] = None
    # The name and arguments of a function that should be called, as generated by the model.
    function_call: Optional[Any] = None
    # Performance in seconds.
    time: Optional[float] = None


class References(BaseModel):
    """Pydantic model for holding LLM references"""

    # The question asked by the user.
    query: str
    # The references from the vector database.
    references: str
    # Performance in seconds.
    time: Optional[float] = None


class Function(BaseModel):
    """Pydantic model for holding LLM functions"""

    # The name of the function to be called.
    # Must be a-z, A-Z, 0-9, or contain underscores and dashes, with a maximum length of 64.
    name: str
    # A description of what the function does, used by the model to choose when and how to call the function.
    description: Optional[str] = None
    # The parameters the functions accepts, described as a JSON Schema object.
    # To describe a function that accepts no parameters, provide the value {"type": "object", "properties": {}}.
    parameters: Dict[str, Any] = {"type": "object", "properties": {}}
    entrypoint: Optional[Callable] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True, exclude={"entrypoint"})
