"""Bundled identity check; certificate generation/profile UI has been removed."""

from .protocol.certs import bundled_app_cert_paths, check_certs_exist


class CertsFlowMixin:
    """Compatibility name for the small fixed transport check."""

    def _resolve_ssl_certs(self):
        self.certfile, self.keyfile = bundled_app_cert_paths()
        self.use_ssl = True
        return check_certs_exist(self.certfile, self.keyfile)

    async def async_step_certs(self, user_input=None):
        return self.async_abort(reason="bundled_certificates_missing")
