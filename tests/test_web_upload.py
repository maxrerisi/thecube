def test_upload_page_renders(client):
    r = client.get("/upload")
    assert r.status_code == 200
    assert "eAccounts transactions" in r.text and 'name="receipt_files"' in r.text


def test_import_eml_files_and_paste(client, fixtures):
    def eml(name):
        return ("receipt_files", (name, (fixtures / name).read_bytes(), "message/rfc822"))

    r = client.post(
        "/upload",
        headers={"HX-Request": "true"},
        files=[eml("receipt_html.eml"), eml("receipt_forwarded_inline.eml")],
        data={"eaccounts_text": (fixtures / "eaccounts_paste.tsv").read_text(), "balance": "1,500.00"},
    )
    assert r.status_code == 200
    assert 'id="import-summary"' in r.text and "<html" not in r.text  # HTMX partial
    assert '<div class="n">2</div><div class="k">new receipts' in r.text
    assert '<div class="n">5</div><div class="k">new transactions' in r.text


def test_summary_counts_and_review(loaded_client):
    page = loaded_client.get("/upload").text
    assert "8 receipts · 20 transactions" in page
    assert 'aria-label="3 to review"' in page


def test_reimport_reports_duplicates(loaded_client, fixtures):
    r = loaded_client.post("/upload", data={"eaccounts_text": (fixtures / "eaccounts.csv").read_text()})
    assert '<div class="n">0</div><div class="k">new transactions<br>20 already had' in r.text


def test_bad_input_is_reported_not_crashing(client):
    r = client.post(
        "/upload",
        files=[("receipt_files", ("x.eml", b"Subject: hi\n\nhello", "message/rfc822"))],
        data={"eaccounts_text": "garbage\tonly", "balance": "abc"},
    )
    assert r.status_code == 200
    assert "Couldn't read some input" in r.text
    assert "x.eml" in r.text and "isn&#39;t a number" in r.text


def test_empty_submit(client):
    assert "Nothing to import" in client.post("/upload", data={}).text
