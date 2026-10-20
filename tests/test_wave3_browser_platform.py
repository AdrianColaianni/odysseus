"""Wave 3 metadata requires a real allowlisted Linux producer artifact."""
import pytest
from src import browser_identity as browser
from src.agent_runtime.resources import ResourceIdentityError


async def test_unsupported_platform_fails_before_producer_execution(monkeypatch):
    for system, machine in [
        ('Darwin', 'x86_64'),
        ('Windows', 'AMD64'),
        ('Linux', 'riscv64'),
    ]:
        monkeypatch.setattr(browser.platform, 'system', lambda: system)
        monkeypatch.setattr(browser.platform, 'machine', lambda: machine)
        async def forbidden(*args, **kwargs): pytest.fail('Unsupported producer was executed')
        monkeypatch.setattr(browser, 'run_client', forbidden)
        with pytest.raises(ResourceIdentityError, match='Unsupported browser producer platform'):
            await browser.trusted_producer()
