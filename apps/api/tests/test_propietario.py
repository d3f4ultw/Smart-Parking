from __future__ import annotations

from typing import cast

from sqlalchemy.orm import Session

from app.cli import propietario, propietario_web
from app.core.config import get_settings
from app.servicios.gestion_propietario import ResultadoEmisionGestion


def test_entrada_historica_delega_al_emisor_web() -> None:
    assert propietario.main is propietario_web.main


def test_emisor_publica_ticket_en_fragmento_y_codigo_separado(
    monkeypatch,
    capsys,
) -> None:
    resultado = ResultadoEmisionGestion(
        estado="emitida",
        ticket="ticket-sintetico",
        codigo_apareamiento="ABCDEFGHJKLMNPQR",
    )
    monkeypatch.setattr(propietario_web, "emitir_sesion_gestion", lambda _db: resultado)

    salida = propietario_web.main(
        db=cast(Session, object()),
        settings=get_settings(),
    )

    lineas = capsys.readouterr().out.splitlines()
    assert salida == 0
    assert lineas[0] == "STATUS=READY"
    assert "/admin/gestion-propietario#ticket-sintetico" in lineas[1]
    assert lineas[2] == "PAIRING_CODE=ABCD-EFGH-JKLM-NPQR"
    assert all(
        "PAIRING_CODE" not in linea or "ticket-sintetico" not in linea
        for linea in lineas
    )


def test_emisor_activo_no_revela_una_nueva_url_ni_codigo(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        propietario_web,
        "emitir_sesion_gestion",
        lambda _db: ResultadoEmisionGestion(estado="activa"),
    )

    salida = propietario_web.main(
        db=cast(Session, object()),
        settings=get_settings(),
    )

    contenido = capsys.readouterr().out
    assert salida == 0
    assert "STATUS=ACTIVE" in contenido
    assert "URL=" not in contenido
    assert "PAIRING_CODE=" not in contenido
