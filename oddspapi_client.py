
from __future__ import annotations
import os, requests

BASE_URL = "https://api.oddspapi.io/v4"

class OddsPapiError(RuntimeError):
    pass

class OddsPapiClient:
    def __init__(self, api_key=None, timeout=30):
        self.api_key = api_key or os.getenv("ODDSPAPI_KEY")
        if not self.api_key:
            raise OddsPapiError("ODDSPAPI_KEY is not set.")
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, endpoint, **params):
        params = {k:v for k,v in params.items() if v is not None}
        params["apiKey"] = self.api_key
        r = self.session.get(
            f"{BASE_URL}/{endpoint.lstrip('/')}",
            params=params,
            timeout=self.timeout
        )
        try:
            payload = r.json()
        except Exception:
            raise OddsPapiError(f"Non-JSON response from {endpoint}: {r.text[:500]}")
        if not r.ok:
            raise OddsPapiError(f"OddsPapi HTTP {r.status_code}: {payload}")
        return payload

    def fixtures(self, sport_id, date_from, date_to, status_id=0, has_odds=True, language="en"):
        return self._get(
            "fixtures",
            sportId=sport_id,
            **{
                "from": date_from,
                "to": date_to,
                "statusId": status_id,
                "hasOdds": str(bool(has_odds)).lower(),
                "language": language,
            }
        )
