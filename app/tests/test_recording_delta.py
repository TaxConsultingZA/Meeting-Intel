import httpx
import pytest
import respx
from app.graph import client


@pytest.fixture(autouse=True)
def graph_mode(monkeypatch):
    monkeypatch.setattr(client,"_mock_enabled",lambda:False)
    monkeypatch.setattr(client,"get_token",lambda:"offline")


@respx.mock
async def test_delta_resumes_bounded_pages_and_complete_checkpoint():
    prefix=f"{client.settings.graph_base}/drives/owned/"
    initial=respx.get(url__regex=r".*/items/folder/delta.*").mock(return_value=httpx.Response(200,json={
        "value":[{"id":"first","name":"first.mp4"}],"@odata.nextLink":prefix+"items/folder/page2"}))
    respx.get(prefix+"items/folder/page2").mock(return_value=httpx.Response(200,json={
        "value":[{"id":"second","name":"second.MP4"}],"@odata.deltaLink":prefix+"items/folder/checkpoint"}))
    rows,cursor,done,calls=await client.recording_delta("owned","folder",max_pages=1)
    assert [r["id"] for r in rows]==["first"] and not done and calls==1
    rows,cursor,done,calls=await client.recording_delta("owned","folder",cursor,max_pages=1)
    assert [r["id"] for r in rows]==["second"] and done and cursor.endswith("checkpoint")


@respx.mock
async def test_expired_delta_restarts_once_and_foreign_cursor_never_receives_token():
    base=f"{client.settings.graph_base}/drives/owned/"
    respx.get(base+"expired").mock(return_value=httpx.Response(410))
    respx.get(url__regex=r".*/items/folder/delta.*").mock(return_value=httpx.Response(200,json={
        "value":[],"@odata.deltaLink":base+"fresh"}))
    _,cursor,complete,calls=await client.recording_delta("owned","folder",base+"expired")
    assert complete and cursor==base+"fresh" and calls==2
    with pytest.raises(RuntimeError,match="Invalid"):
        await client.recording_delta("owned","folder","https://untrusted.example/token")


@respx.mock
async def test_incremental_roots_include_previously_supported_nested_recordings():
    base=f"{client.settings.graph_base}/drives/owned/"
    for path in ("Recordings","Documents/Recordings"):
        respx.get(base+f"root:/{path}?$select=id,folder").mock(return_value=httpx.Response(404))
    respx.get(base+"root/children?$select=id,name,folder").mock(return_value=httpx.Response(200,json={
        "value":[{"id":"organized","name":"Personal project files","folder":{}}]}))
    respx.get(base+"items/organized/children?$select=id,name,folder").mock(return_value=httpx.Response(200,json={
        "value":[{"id":"nested-recordings","name":"Recordings","folder":{}}]}))
    assert await client.recording_roots("owned")==["nested-recordings"]
