from homeassistant import config_entries

class DabFranceMetadataConfigFlow(config_entries.ConfigFlow, domain="dab_france_metadata"):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id("dab_france_metadata")
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="DAB+ France Metadata", data={})
        return self.async_show_form(step_id="user")
