"""La UI trae la seccion de Jira, el token va en un campo oculto y la pagina no lo guarda
en sessionStorage (igual que el token admin)."""

from __future__ import annotations

from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "app" / "ui" / "index.html").read_text("utf-8")


def test_seccion_jira_con_campos_y_endpoints() -> None:
    for id_ in (
        "jira-sitio",
        "jira-correo",
        "jira-token",
        "jira-tablero",
        "jira-entrada",
        "jira-resuelto",
        "jira-escalado",
        "jira-intervalo",
        "jira-activar",
    ):
        assert f'id="{id_}"' in HTML
    assert 'id="jira-token" type="password"' in HTML
    for ruta in (
        "/config/jira/conexion",
        "/config/jira/probar",
        "/config/jira/tableros",
        "/config/jira/tablero",
        "/config/jira/activo",
    ):
        assert ruta in HTML


def test_el_token_de_jira_no_se_guarda_en_el_navegador() -> None:
    assert 'guardar("jira' not in HTML and "localStorage" not in HTML


def test_el_script_de_jira_esta_a_nivel_superior_fuera_del_listener_del_llm() -> None:
    inicio = HTML.index('$("llm-probar").addEventListener')
    fin = HTML.index("});", HTML.index("r.ok", inicio))
    assert HTML.index('$("jira-guardar").addEventListener') > fin
    ok = HTML.index("r.ok", inicio)
    assert inicio < HTML.index("/config/llm/probar") < ok < HTML.index("// --- Jira")
