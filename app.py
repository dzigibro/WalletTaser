from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Flask, jsonify, redirect, render_template, request, url_for

from persistence import TransactionReprocessor, VendorTagRepository

app = Flask(__name__)

repo = VendorTagRepository()
repo.migrate_from_csv()
reprocessor = TransactionReprocessor(repo)


def resolve_user_id() -> str:
    return (
        request.headers.get('X-User-Id')
        or request.args.get('user_id')
        or request.form.get('user_id')
        or 'default'
    )


@app.route('/')
def index() -> str:
    user_id = resolve_user_id()
    tags = repo.list_tags(user_id)
    return render_template('vendor_tags.html', tags=tags, user_id=user_id)


@app.get('/api/vendor-tags')
def list_vendor_tags() -> Any:
    user_id = resolve_user_id()
    return jsonify(repo.list_tags(user_id))


def _parse_payload(data: Dict[str, Any]) -> Dict[str, str]:
    vendor = (data.get('vendor') or '').upper().strip()
    cls = (data.get('class') or '').upper().strip()
    if cls not in {'NEEDS', 'WANTS'}:
        raise ValueError('class must be NEEDS or WANTS')
    if not vendor:
        raise ValueError('vendor is required')
    return {'vendor': vendor, 'class': cls}


@app.post('/api/vendor-tags')
def create_or_update_tag() -> Any:
    user_id = resolve_user_id()
    data = request.get_json(silent=True) or request.form.to_dict()
    try:
        payload = _parse_payload(data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    repo.set_tag(user_id, payload['vendor'], payload['class'])
    reprocessor.schedule(user_id, payload['vendor'])
    return jsonify({'status': 'ok', 'vendor': payload['vendor'], 'class': payload['class']})


@app.delete('/api/vendor-tags/<vendor>')
def delete_tag(vendor: str) -> Any:
    user_id = resolve_user_id()
    vendor = vendor.upper()
    repo.delete_tag(user_id, vendor)
    reprocessor.schedule(user_id, vendor)
    return jsonify({'status': 'ok', 'vendor': vendor})


@app.post('/ui/vendor-tags')
def ui_create_tag() -> Any:
    response = create_or_update_tag()
    if isinstance(response, tuple):
        return response
    user_id = resolve_user_id()
    return redirect(url_for('index', user_id=user_id))


@app.post('/ui/vendor-tags/<vendor>/delete')
def ui_delete_tag(vendor: str) -> Any:
    delete_tag(vendor)
    user_id = resolve_user_id()
    return redirect(url_for('index', user_id=user_id))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True)
