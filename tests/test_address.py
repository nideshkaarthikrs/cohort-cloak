from cloak.detect.address import rewrite_address


def test_english_address_segments():
    out, n = rewrite_address("Makan No. 143, near Kali Mata Mandir, Vill. Jalalnagar Khurd, Tehsil Dalmau, Distt. Rae Bareli - 229678")
    assert "143" not in out and "Kali" not in out and "Jalalnagar" not in out
    assert "Tehsil Dalmau" in out and "Distt. Rae Bareli" in out
    assert "229678" not in out and "229***" in out
    assert n >= 3


def test_hindi_address():
    out, _ = rewrite_address("मकान नं. 32, जामा मस्जिद के पीछे, ग्राम अमरगंज खुर्द, तहसील X, जिला बाराबंकी - 225127")
    assert "32" not in out and "जामा" not in out and "अमरगंज" not in out
    assert "तहसील X" in out and "जिला बाराबंकी" in out and "225***" in out


def test_unknown_segment_fails_closed():
    out, _ = rewrite_address("Plot 9 Sector 4, Some Colony, Distt. Hardoi")
    assert "Plot 9" not in out and "Some Colony" not in out and "Distt. Hardoi" in out


def test_pin_redact_mode():
    out, _ = rewrite_address("H.No. 5, Distt. X - 229678", pin_mode="redact")
    assert "229" not in out
