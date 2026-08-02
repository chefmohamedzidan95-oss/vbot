import logging
from typing import Dict, List, Optional
from .base import BaseProvider
from .qfilm import QfilmProvider

logger = logging.getLogger(__name__)


class ProviderManager:
    """
    Registry and Manager for Movie & Series providers/sources.
    Enables modular addition of new providers and switching active providers.
    """

    def __init__(self, config_path: str = "config.json"):
        self.providers: Dict[str, BaseProvider] = {}
        self.config_path = config_path

        # Register default built-in providers
        self.register_provider(QfilmProvider(config_path=config_path))

    def register_provider(self, provider: BaseProvider):
        """Register a new provider instance."""
        self.providers[provider.id] = provider
        logger.info(f"Registered provider: {provider.id} ({provider.name})")

    def get_provider(self, provider_id: str) -> Optional[BaseProvider]:
        """Get provider by ID, or fallback to default provider."""
        if provider_id in self.providers:
            return self.providers[provider_id]
        
        # Fallback to first available provider
        if self.providers:
            return list(self.providers.values())[0]
        return None

    def list_providers(self) -> List[BaseProvider]:
        """Return list of all registered providers."""
        return list(self.providers.values())
