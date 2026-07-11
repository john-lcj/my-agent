"""Deterministic local pages used by P5 browser regression tests."""

LOGIN_FORM = """<!doctype html><html><body>
<h1>Local Browser Fixture</h1>
<form id='fixture-form'><label for='name'>Name</label><input id='name' name='name'>
<label for='secret'>Secret</label><input id='secret' name='secret' type='password'>
<button type='submit'>Save</button></form><p id='result' hidden>Saved successfully</p>
<script>document.querySelector('form').onsubmit=(e)=>{e.preventDefault();document.querySelector('#result').hidden=false}</script>
</body></html>"""


def fixture_contract() -> dict[str, object]:
    return {
        "name": "login-form",
        "html": LOGIN_FORM,
        "required_roles": ["heading", "textbox", "button"],
        "success_text": "Saved successfully",
        "secret_fields": ["secret"],
    }
