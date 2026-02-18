import pytest

from app.storage.local import LocalStorage


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(str(tmp_path))


@pytest.mark.asyncio
async def test_write_and_read(storage):
    await storage.write_bytes("test/file.txt", b"hello world")
    data = await storage.read_bytes("test/file.txt")
    assert data == b"hello world"


@pytest.mark.asyncio
async def test_read_missing_raises(storage):
    with pytest.raises(FileNotFoundError):
        await storage.read_bytes("does/not/exist.txt")


@pytest.mark.asyncio
async def test_exists(storage):
    assert not await storage.exists("test/file.txt")
    await storage.write_bytes("test/file.txt", b"data")
    assert await storage.exists("test/file.txt")


@pytest.mark.asyncio
async def test_delete(storage):
    await storage.write_bytes("test/file.txt", b"data")
    assert await storage.exists("test/file.txt")
    await storage.delete("test/file.txt")
    assert not await storage.exists("test/file.txt")


@pytest.mark.asyncio
async def test_delete_missing_no_error(storage):
    await storage.delete("does/not/exist.txt")


@pytest.mark.asyncio
async def test_list_keys(storage):
    await storage.write_bytes("prefix/a.txt", b"a")
    await storage.write_bytes("prefix/b.txt", b"b")
    await storage.write_bytes("prefix/sub/c.txt", b"c")
    await storage.write_bytes("other/d.txt", b"d")

    keys = await storage.list_keys("prefix")
    assert keys == ["prefix/a.txt", "prefix/b.txt", "prefix/sub/c.txt"]


@pytest.mark.asyncio
async def test_list_keys_empty_prefix(storage):
    keys = await storage.list_keys("nonexistent")
    assert keys == []


@pytest.mark.asyncio
async def test_get_download_url(storage):
    await storage.write_bytes("out/file.pptx", b"pptx bytes")
    url = await storage.get_download_url("out/file.pptx")
    assert "file.pptx" in url


@pytest.mark.asyncio
async def test_get_download_url_missing_raises(storage):
    with pytest.raises(FileNotFoundError):
        await storage.get_download_url("missing.pptx")


@pytest.mark.asyncio
async def test_atomic_write(storage, tmp_path):
    """Write should be atomic — no partial file on success."""
    await storage.write_bytes("atomic/test.bin", b"x" * 1000)
    data = await storage.read_bytes("atomic/test.bin")
    assert len(data) == 1000
    # No .tmp file should remain
    tmp_files = list(tmp_path.rglob("*.tmp"))
    assert tmp_files == []
