"""Compatibility import for the pre-1.4 settings page entry point."""

from ui.pages.community_settings_page import CommunitySettingsPage


UnifiedSettingsPage = CommunitySettingsPage

__all__ = ["UnifiedSettingsPage"]
