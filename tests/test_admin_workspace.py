import importlib
import io

import pytest
import yaml

backend = importlib.import_module('app.app')


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(backend, 'CONFIG_DIR', tmp_path)
    monkeypatch.setattr(backend, 'BASE_DIR', tmp_path)
    monkeypatch.setattr(backend, 'YAML_CACHE', {})
    for name, section in backend.ADMIN_SECTIONS.items():
        (tmp_path / name).write_text(yaml.safe_dump({} if section.get('kind') == 'doc' else []))
    (tmp_path / 'slides.yaml').write_text(yaml.safe_dump([{'image': 'images/slide.jpg', 'headline': 'Vereinsabend'}]))
    with backend.app.test_client() as client:
        with client.session_transaction() as session:
            session['logged_in'] = True
        yield client, tmp_path


def test_workspace_navigation_and_all_editors(workspace):
    client, _ = workspace
    html = client.get('/admin').get_data(as_text=True)
    assert 'CONTENT STUDIO' in html
    assert 'Website gestalten' in html
    assert 'Beitrag erstellen' in html
    for name, section in backend.ADMIN_SECTIONS.items():
        if section.get('kind') == 'doc':
            urls = [f'/admin/doc/{name}']
        else:
            urls = [f'/admin/manage/{name}']
            if section.get('allow_new'):
                urls.append(f'/admin/manage/{name}/new')
        for url in urls:
            response = client.get(url)
            assert response.status_code == 200, url
            assert b'studio-sidebar' in response.data
            assert b'aria-current="page"' in response.data
    assert client.get('/admin/media').status_code == 200
    assert client.get('/admin/edit/slides.yaml').status_code == 200


def test_media_upload_and_index(workspace):
    client, directory = workspace
    response = client.post('/admin/upload', data={'image': (io.BytesIO(b'image-data'), 'new-image.png')})
    assert response.status_code == 302
    assert response.location.endswith('/admin/media')
    assert (directory / 'static/images/new-image.png').read_bytes() == b'image-data'
    assert client.get('/admin/images.json').json[0]['name'] == 'new-image.png'


def test_media_upload_failure_is_actionable(workspace, monkeypatch):
    from werkzeug.datastructures import FileStorage
    client, _ = workspace

    def fail(*args, **kwargs):
        raise PermissionError('read only')

    monkeypatch.setattr(FileStorage, 'save', fail)
    response = client.post('/admin/upload', data={'image': (io.BytesIO(b'image-data'), 'new.png')}, follow_redirects=True)
    assert response.status_code == 200
    assert 'konnte nicht gespeichert werden' in response.get_data(as_text=True)


def test_media_requires_login():
    with backend.app.test_client() as client:
        assert client.get('/admin/media').status_code == 302
