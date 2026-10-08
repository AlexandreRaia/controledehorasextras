"""Cliente HTTP minimo para a API do Baserow.

Linhas sao lidas/gravadas com ``user_field_names=true``, entao usamos os nomes
das colunas como aparecem na interface. Metadados (listar tabelas e campos,
criar campos) exigem autenticacao JWT com e-mail e senha.
"""
import json
import os
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".baserow_cache.json")


def nova_sessao(tentativas=4):
    """Sessao HTTP que repete sozinha em timeout de conexao e erro 5xx."""
    sessao = requests.Session()
    politica = Retry(
        total=tentativas,
        connect=tentativas,
        read=0,  # nao repete depois que o pedido chegou: evitaria linha duplicada
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "PATCH", "DELETE"]),
    )
    adaptador = HTTPAdapter(max_retries=politica, pool_connections=4, pool_maxsize=8)
    sessao.mount("https://", adaptador)
    sessao.mount("http://", adaptador)
    return sessao


class BaserowError(RuntimeError):
    def __init__(self, message, status=None, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class BaserowClient:
    def __init__(self, base_url, email=None, password=None, token=None, timeout=30):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.token = token
        self.timeout = timeout
        self._jwt = None
        self._jwt_exp = 0
        self._refresh_token = None
        self._lock = threading.Lock()
        self._session = nova_sessao()

    # ------------------------------------------------------------------ auth
    def _login(self):
        if not (self.email and self.password):
            raise BaserowError(
                "BASEROW_EMAIL e BASEROW_PASSWORD precisam estar preenchidos no .env "
                "para ler o esquema do Baserow."
            )
        resp = self._session.post(
            f"{self.base_url}/api/user/token-auth/",
            json={"email": self.email, "password": self.password},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise BaserowError(
                f"Falha ao autenticar no Baserow ({resp.status_code}). Verifique e-mail e senha.",
                resp.status_code,
                _safe_json(resp),
            )
        data = resp.json()
        self._jwt = data.get("access_token") or data.get("token")
        self._refresh_token = data.get("refresh_token")
        self._jwt_exp = time.time() + 9 * 60

    def jwt(self):
        with self._lock:
            if not self._jwt or time.time() >= self._jwt_exp:
                if self._refresh_token:
                    try:
                        self._refresh()
                    except BaserowError:
                        self._login()
                else:
                    self._login()
            return self._jwt

    def _refresh(self):
        resp = self._session.post(
            f"{self.base_url}/api/user/token-refresh/",
            json={"refresh_token": self._refresh_token},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise BaserowError("Nao foi possivel renovar o token JWT.", resp.status_code)
        data = resp.json()
        self._jwt = data.get("access_token") or data.get("token")
        self._jwt_exp = time.time() + 9 * 60

    def _headers(self, force_jwt=False):
        if not force_jwt and self.token:
            return {"Authorization": f"Token {self.token}"}
        return {"Authorization": f"JWT {self.jwt()}"}

    # --------------------------------------------------------------- request
    def _request(self, method, path, force_jwt=False, **kwargs):
        url = f"{self.base_url}{path}"
        headers = self._headers(force_jwt)
        headers.update(kwargs.pop("headers", {}))
        resp = self._session.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        if resp.status_code == 401 and not force_jwt and self.token:
            # token de banco sem permissao: tenta novamente via JWT
            resp = self._session.request(
                method, url, headers=self._headers(True), timeout=self.timeout, **kwargs
            )
        if resp.status_code >= 400:
            raise BaserowError(
                _describe_error(resp), resp.status_code, _safe_json(resp)
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ------------------------------------------------------------- metadados
    def list_applications(self):
        return self._request("GET", "/api/applications/", force_jwt=True)

    def list_tables(self, database_id):
        return self._request("GET", f"/api/database/tables/database/{database_id}/", force_jwt=True)

    def list_fields(self, table_id):
        return self._request("GET", f"/api/database/fields/table/{table_id}/", force_jwt=True)

    def create_field(self, table_id, payload):
        return self._request(
            "POST", f"/api/database/fields/table/{table_id}/", force_jwt=True, json=payload
        )

    def update_field(self, field_id, payload):
        return self._request(
            "PATCH", f"/api/database/fields/{field_id}/", force_jwt=True, json=payload
        )

    # ----------------------------------------------------------------- linhas
    def list_rows(self, table_id, filters=None, order_by=None, search=None, size=200, limit=None):
        params = {"user_field_names": "true", "size": size}
        if order_by:
            params["order_by"] = order_by
        if search:
            params["search"] = search
        for key, value in (filters or {}).items():
            params[key] = value

        rows = []
        url = f"/api/database/rows/table/{table_id}/"
        while url:
            data = self._request("GET", url, params=params)
            rows.extend(data.get("results", []))
            if limit and len(rows) >= limit:
                return rows[:limit]
            nxt = data.get("next")
            if not nxt:
                break
            url = nxt[len(self.base_url):] if nxt.startswith(self.base_url) else nxt
            params = None
        return rows

    def count_rows(self, table_id, filters=None):
        """Quantas linhas a tabela tem, opcionalmente sob um filtro."""
        params = {"user_field_names": "true", "size": 1}
        params.update(filters or {})
        data = self._request("GET", f"/api/database/rows/table/{table_id}/", params=params)
        return (data or {}).get("count", 0)

    def get_row(self, table_id, row_id):
        return self._request(
            "GET",
            f"/api/database/rows/table/{table_id}/{row_id}/",
            params={"user_field_names": "true"},
        )

    def create_row(self, table_id, data):
        return self._request(
            "POST",
            f"/api/database/rows/table/{table_id}/",
            params={"user_field_names": "true"},
            json=data,
        )

    def update_row(self, table_id, row_id, data):
        return self._request(
            "PATCH",
            f"/api/database/rows/table/{table_id}/{row_id}/",
            params={"user_field_names": "true"},
            json=data,
        )

    def delete_row(self, table_id, row_id):
        return self._request("DELETE", f"/api/database/rows/table/{table_id}/{row_id}/")


def _safe_json(resp):
    try:
        return resp.json()
    except ValueError:
        return {"detail": resp.text[:400]}


def _describe_error(resp):
    payload = _safe_json(resp)
    detail = payload.get("detail") or payload.get("error") or payload
    return f"Baserow respondeu {resp.status_code}: {detail}"


# ------------------------------------------------------------------ cache ids
def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_cache(data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass
