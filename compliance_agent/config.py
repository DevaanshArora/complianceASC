from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # LLM Provider Selection
    llm_provider: str = "groq"  # Options: "ollama", "groq"

    # Ollama Configuration
    ollama_base_url: str = "https://ollama-serve.ascentbusiness.com"
    ollama_model: str = "mistral:latest"

    # Groq Configuration
    groq_api_key: Optional[str] = None
    groq_model: str = "llama-3.1-8b-instant"

    # Shared LLM Settings
    temperature: float = 0.1

    # Processing Configuration
    max_workers: int = 6
    chunk_overlap: int = 200

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False

    def validate_llm_provider(self) -> None:
        """Validate LLM provider configuration."""
        if self.llm_provider not in ["ollama", "groq"]:
            raise ValueError(f"Invalid llm_provider: {self.llm_provider}. Must be 'ollama' or 'groq'")

        if self.llm_provider == "groq" and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when llm_provider is 'groq'")


settings = Settings()
