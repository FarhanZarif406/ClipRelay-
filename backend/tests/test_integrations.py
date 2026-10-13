import httpx
import respx

from app.integrations import http
from app.security import decrypt, encrypt
from app.services import prompts


@respx.mock
def test_http_retries_with_backoff():
    route = respx.get("https://x.test/").mock(side_effect=[httpx.Response(503), httpx.Response(429), httpx.Response(200, json={})])
    assert http.request("GET", "https://x.test/").status_code == 200
    assert route.call_count == 3


def test_backoff_grows_exponentially():
    assert http.backoff_delay(0, base=1) <= 1
    assert 4 <= http.backoff_delay(3, base=1) * 2 <= 16
    assert http.backoff_delay(30, base=1, cap=60) <= 60


def test_token_encryption_roundtrip():
    secret = "IGQVJ-very-secret"
    stored = encrypt(secret)
    assert stored != secret and decrypt(stored) == secret


def test_prompt_render_variables_and_aliases():
    out = prompts.render("Rewrite {caption} / {original_title} / {tags} / {unknown}", {"caption": "C", "title": "T", "tags": "#a"})
    assert out == "Rewrite C / T / #a / {unknown}"
    assert prompts.parse_hashtags("#Crete #hidden_gems greece #crete") == ["crete", "hidden_gems", "greece"]
