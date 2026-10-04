from unittest.mock import patch

import pytest

from app.seguridad.contrasenas import (
    CARACTERES_CONTRASENA_TEMPORAL,
    CARACTERES_MAYUSCULAS_CONTRASENA,
    LONGITUD_CONTRASENA_OPERADOR,
    LONGITUD_CONTRASENA_TEMPORAL,
    ContrasenaInvalidaError,
    generar_contrasena_operador,
    generar_contrasena_temporal,
    validar_contrasena,
)


def test_contrasena_de_10_caracteres_con_mayuscula_es_valida() -> None:
    validar_contrasena("Abcdefghij")


def test_contrasena_de_9_caracteres_es_rechazada() -> None:
    with pytest.raises(
        ContrasenaInvalidaError,
        match="al menos 10 caracteres",
    ):
        validar_contrasena("Abcdefghi")


def test_contrasena_sin_mayuscula_es_rechazada() -> None:
    with pytest.raises(
        ContrasenaInvalidaError,
        match="letra mayúscula",
    ):
        validar_contrasena("abcdefghij")


def test_contrasena_larga_con_mayuscula_es_valida() -> None:
    validar_contrasena("MiPasswordSegura")


def test_contrasenas_temporales_tienen_14_caracteres() -> None:
    contrasenas = [generar_contrasena_temporal() for _ in range(32)]

    assert all(
        len(contrasena) == LONGITUD_CONTRASENA_TEMPORAL for contrasena in contrasenas
    )
    assert all(
        all(caracter in CARACTERES_CONTRASENA_TEMPORAL for caracter in contrasena)
        for contrasena in contrasenas
    )


def test_contrasena_temporal_usa_secrets_choice() -> None:
    with patch(
        "app.seguridad.contrasenas.secrets.choice",
        return_value="A",
    ) as elegir:
        contrasena = generar_contrasena_temporal()

    assert contrasena == "A" * LONGITUD_CONTRASENA_TEMPORAL
    assert elegir.call_count == LONGITUD_CONTRASENA_TEMPORAL
    assert all(
        llamada.args == (CARACTERES_CONTRASENA_TEMPORAL,)
        for llamada in elegir.call_args_list
    )


def test_contrasenas_de_operador_son_de_16_caracteres_y_validas() -> None:
    contrasenas = [generar_contrasena_operador() for _ in range(32)]

    assert all(
        len(contrasena) == LONGITUD_CONTRASENA_OPERADOR for contrasena in contrasenas
    )
    assert all(
        any(caracter.isupper() for caracter in contrasena) for contrasena in contrasenas
    )
    assert all(
        all(caracter in CARACTERES_CONTRASENA_TEMPORAL for caracter in contrasena)
        for contrasena in contrasenas
    )
    for contrasena in contrasenas:
        validar_contrasena(contrasena)


def test_generador_de_operador_usa_csprng_y_fuerza_una_mayuscula() -> None:
    with (
        patch(
            "app.seguridad.contrasenas.secrets.randbelow",
            return_value=5,
        ) as posicion,
        patch(
            "app.seguridad.contrasenas.secrets.choice",
            side_effect=lambda caracteres: (
                "A" if caracteres == CARACTERES_MAYUSCULAS_CONTRASENA else "a"
            ),
        ) as elegir,
    ):
        contrasena = generar_contrasena_operador()

    assert len(contrasena) == LONGITUD_CONTRASENA_OPERADOR
    assert contrasena[5] == CARACTERES_MAYUSCULAS_CONTRASENA[0]
    assert contrasena.count(CARACTERES_MAYUSCULAS_CONTRASENA[0]) == 1
    posicion.assert_called_once_with(LONGITUD_CONTRASENA_OPERADOR)
    assert elegir.call_count == LONGITUD_CONTRASENA_OPERADOR
