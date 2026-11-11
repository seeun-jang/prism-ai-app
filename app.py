"""PRISM AI screen. API_URL and APP_ACCESS_CODE belong in Streamlit Secrets."""
import hashlib
import json
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
import streamlit as st
from pypdf import PdfReader

DEFAULT_QUESTION = "연구 핵심과 실제 사용한 데이터셋을 원문 근거와 함께 정리해 주세요."
FIELDS = ["사용 목적", "규모", "데이터 분할", "전처리", "접근 링크"]
SAMPLE_TEXT = ("기능 시험용 가상 논문이며 실제 연구 결과가 아닙니다. "
               "연구 목적은 센서 기록의 동작 유형 분류입니다. "
               "실험에는 가상 데이터셋 SensorDemo를 사용했습니다. "
               "SensorDemo는 기록 200개로 구성됩니다. "
               "데이터는 학습 80%, 테스트 20%로 분할했습니다. "
               "비교 방법은 로지스틱 회귀와 작은 신경망입니다.")


def settings():
    try:
        url = str(st.secrets.get("API_URL", "")).strip().rstrip("/")
        code = str(st.secrets.get("APP_ACCESS_CODE", "")).strip()
    except Exception:
        return "", "", "Streamlit Secrets에 API_URL과 APP_ACCESS_CODE를 등록해 주세요."
    parsed = urlparse(url)
    local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    if not parsed.hostname or not (parsed.scheme == "https" or local) or parsed.path or parsed.query or parsed.fragment or parsed.username:
        return "", "", "API_URL에는 /docs나 /ask가 없는 백엔드 기본 주소를 넣어 주세요."
    if not code or not code.isascii():
        return url, "", "APP_ACCESS_CODE에 Vercel과 동일한 영문·숫자 접근 코드를 넣어 주세요."
    return url, code, ""


def api_request(url, code, path, payload=None):
    try:
        response = requests.request("POST" if payload is not None else "GET", url + path,
                                    json=payload, headers={"X-Access-Code": code},
                                    timeout=(10, 90), allow_redirects=False)
    except requests.RequestException:
        raise ValueError("백엔드에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.") from None
    messages = {401: "접근 코드가 다릅니다. Streamlit과 Vercel의 APP_ACCESS_CODE를 확인해 주세요.",
                404: "백엔드 주소와 PRISM 코드 배포 상태를 확인해 주세요.",
                422: "분석 입력 형식을 확인해 주세요. 페이지 범위나 질문을 조정해 주세요.",
                429: "AI 요청 한도에 도달했습니다. 잠시 뒤 다시 시도해 주세요.",
                502: "AI 서버 오류입니다. Vercel 로그에서 Gemini API 키·모델 설정 또는 응답 형식을 확인해 주세요. 페이지 수를 줄이는 것만으로 해결되지 않을 수 있습니다.",
                503: "Vercel의 API 키·접근 코드 설정과 재배포 상태를 확인해 주세요."}
    if response.status_code != 200:
        raise ValueError(messages.get(response.status_code, f"서버 응답을 확인해 주세요. 상태 번호: {response.status_code}"))
    try:
        data = response.json()
    except ValueError:
        raise ValueError("서버가 올바른 JSON을 반환하지 않았습니다. API_URL을 확인해 주세요.") from None
    if not isinstance(data, dict):
        raise ValueError("서버 응답 형식을 확인해 주세요.")
    return data


def open_pdf(raw):
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("8MB 이하의 PDF를 선택해 주세요.")
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError("암호가 없는 PDF로 다시 저장한 뒤 올려 주세요.")
        if not 1 <= len(reader.pages) <= 300:
            raise ValueError("이 버전은 1~300쪽 PDF를 지원합니다.")
        return reader
    except ValueError:
        raise
    except Exception:
        raise ValueError("PDF를 읽지 못했습니다. 정상적인 텍스트 PDF인지 확인해 주세요.") from None


def extract_pages(reader, start, end):
    if not 1 <= start <= end <= len(reader.pages) or end - start + 1 > 60:
        raise ValueError("시작·끝 페이지를 확인해 주세요. 한 번에 최대 60쪽까지 분석합니다.")
    pages, skipped = [], []
    for number in range(start, end + 1):
        try:
            text = (reader.pages[number - 1].extract_text() or "").strip()
        except Exception:
            raise ValueError(f"PDF {number}쪽의 텍스트를 읽지 못했습니다. 다른 범위를 선택해 주세요.") from None
        if not text:
            skipped.append(number)
        elif len(text) > 20000:
            raise ValueError(f"PDF {number}쪽이 너무 큽니다. 텍스트 추출 상태를 확인해 주세요.")
        else:
            pages.append({"page": number, "text": text})
    if not pages:
        raise ValueError("읽을 수 있는 텍스트가 없습니다. 스캔 PDF의 문자 인식은 아직 지원하지 않습니다.")
    if sum(len(p["text"]) for p in pages) > 60000:
        raise ValueError("선택한 본문이 60,000자를 넘습니다. 페이지 범위를 줄여 주세요.")
    return pages, skipped


def signature(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def check_result(data, pages):
    report = data.get("report")
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list) or not isinstance(report.get("datasets"), list):
        raise ValueError("PRISM 분석 결과 형식이 아닙니다. 백엔드 코드를 확인해 주세요.")
    source = {p["page"]: re.sub(r"\s+", " ", p["text"]).strip() for p in pages}
    if (not isinstance(data.get("analyzed_pages"), list) or data["analyzed_pages"] != [p["page"] for p in pages]
            or not isinstance(data.get("warnings"), list) or not all(isinstance(w, str) for w in data["warnings"])):
        raise ValueError("분석 범위나 응답 정보를 확인하지 못했습니다.")
    for finding in report["findings"]:
        if not isinstance(finding, dict) or finding.get("category") not in ["연구 목적", "방법", "결과", "한계"] or not isinstance(finding.get("text"), str):
            raise ValueError("핵심 요약 형식을 확인하지 못했습니다.")
    for dataset in report["datasets"]:
        if not isinstance(dataset, dict) or not isinstance(dataset.get("name"), str) or not isinstance(dataset.get("relation"), str) or not isinstance(dataset.get("facts"), list):
            raise ValueError("데이터셋 결과 형식을 확인하지 못했습니다.")
        if any(not isinstance(f, dict) or f.get("field") not in FIELDS or not isinstance(f.get("text"), str) for f in dataset["facts"]):
            raise ValueError("데이터셋 세부 정보 형식을 확인하지 못했습니다.")
    entries = report["findings"] + report["datasets"]
    entries += [f for d in report["datasets"] for f in d.get("facts", [])]
    for entry in entries:
        evidence = entry.get("evidence", {})
        if not isinstance(evidence, dict):
            raise ValueError("원문 근거 형식을 확인하지 못했습니다.")
        quote = re.sub(r"\s+", " ", str(evidence.get("quote", ""))).strip()
        if not quote or quote not in source.get(evidence.get("page"), ""):
            raise ValueError("원문에서 확인되지 않는 인용이 있습니다. 다시 분석해 주세요.")
    if not entries:
        raise ValueError("추출된 항목이 없습니다. 분석 범위를 확인해 주세요.")
    return data


def preview_data():
    def evidence(quote): return {"page": 1, "quote": quote}
    return {"report": {"findings": [
        {"category": "연구 목적", "text": "센서 기록의 동작 유형 분류", "evidence": evidence("연구 목적은 센서 기록의 동작 유형 분류입니다.")},
        {"category": "방법", "text": "로지스틱 회귀와 작은 신경망을 비교합니다.", "evidence": evidence("비교 방법은 로지스틱 회귀와 작은 신경망입니다.")}],
        "datasets": [{"name": "SensorDemo", "relation": "직접 사용",
                      "evidence": evidence("실험에는 가상 데이터셋 SensorDemo를 사용했습니다."),
                      "facts": [{"field": "규모", "text": "기록 200개", "evidence": evidence("SensorDemo는 기록 200개로 구성됩니다.")},
                                {"field": "데이터 분할", "text": "학습 80% / 테스트 20%", "evidence": evidence("데이터는 학습 80%, 테스트 20%로 분할했습니다.")}]}]},
        "analyzed_pages": [1], "warnings": ["화면 확인용 가상 자료입니다. 실제 논문이나 AI 응답이 아닙니다."],
        "engine": "화면 예시 · AI 요청 없음", "sample_type": "가상 예시", "tokens": None}


def select_evidence(evidence):
    st.session_state["evidence"] = evidence


def store_result(data, pages, name, request_id, demo=False):
    st.session_state["result"] = {"data": data, "pages": pages, "name": name, "request_id": request_id, "demo": demo}
    report = data["report"]
    first = (report["findings"] + report["datasets"])[0]
    select_evidence(first["evidence"])


def export_notes(result):
    data = result["data"]
    lines = ["# PRISM AI 논문 정리", "", "문서: " + result["name"],
             "분석한 PDF 쪽: " + ", ".join(map(str, data["analyzed_pages"])),
             "처리 방식: " + data.get("engine", ""), ""]
    for item in data["report"]["findings"]:
        lines += ["## " + item["category"], item["text"],
                  f"근거: PDF {item['evidence']['page']}쪽", item["evidence"]["quote"], ""]
    for dataset in data["report"]["datasets"]:
        lines += ["## 데이터셋: " + dataset["name"], "관계: " + dataset["relation"],
                  f"근거: PDF {dataset['evidence']['page']}쪽", dataset["evidence"]["quote"]]
        for fact in dataset.get("facts", []):
            lines += [fact["field"] + ": " + fact["text"],
                      f"근거: PDF {fact['evidence']['page']}쪽", fact["evidence"]["quote"]]
        lines.append("")
    lines += ["## 확인 사항"] + data.get("warnings", [])
    return "\n\n".join(lines)


def show_result(result):
    data, report = result["data"], result["data"]["report"]
    st.subheader("논문 읽기")
    st.text(result["name"])
    if result["demo"]:
        st.info("화면 예시 · 가상 자료 · AI 요청 없음")
    st.caption("분석한 PDF 쪽: " + ", ".join(map(str, data["analyzed_pages"])))
    nav, content, source = st.columns([1, 3, 1.8], gap="large")
    with nav:
        view = st.radio("정리 항목", ["핵심 요약", "데이터셋", "재현 준비", "내보내기"], key="reader_view")
    def cite(evidence, key):
        st.button(f"PDF {evidence['page']}쪽 근거 보기 ↗", key=key,
                  on_click=select_evidence, args=(evidence,))
    with content:
        if view == "핵심 요약":
            for category in ["연구 목적", "방법", "결과", "한계"]:
                st.markdown("### " + category)
                found = [f for f in report["findings"] if f["category"] == category]
                if not found: st.caption("확인되지 않음 · 원문을 확인해 주세요.")
                for i, item in enumerate(found):
                    st.text(item["text"])
                    cite(item["evidence"], f"finding-{category}-{i}")
        elif view == "데이터셋":
            if not report["datasets"]: st.info("데이터셋이 추출되지 않았습니다. 원문과 분석 범위를 확인해 주세요.")
            for i, dataset in enumerate(report["datasets"]):
                with st.container(border=True):
                    st.text("데이터셋 · " + dataset["name"])
                    st.caption("논문과의 관계: " + dataset["relation"])
                    cite(dataset["evidence"], f"dataset-{i}")
                    for field in FIELDS:
                        facts = [f for f in dataset.get("facts", []) if f["field"] == field]
                        if not facts: st.caption(field + ": 확인되지 않음")
                        for j, fact in enumerate(facts):
                            st.text(field + ": " + fact["text"])
                            if field == "접근 링크" and re.fullmatch(r"https?://[^\s<>]+", fact["text"]):
                                st.link_button("원문에 기재된 링크 열기", fact["text"])
                            cite(fact["evidence"], f"fact-{i}-{field}-{j}")
        elif view == "재현 준비":
            st.caption("아래 항목은 준비 점검용이며 실험 실행 완료를 뜻하지 않습니다.")
            for dataset in report["datasets"]:
                st.text("데이터셋 · " + dataset["name"])
                for field in ["접근 링크", "데이터 분할", "전처리"]:
                    facts = [f for f in dataset.get("facts", []) if f["field"] == field]
                    st.text(field + ": " + (" / ".join(f["text"] for f in facts) if facts else "원문·공식 자료에서 추가 확인"))
            st.text("추가 확인: 코드 버전, 실행 환경, 모델 설정, 평가 지표")
        else:
            st.caption("파일에는 정리 결과와 인용 구절이 들어갑니다. 접근 코드는 포함하지 않습니다.")
            st.download_button("연구 노트 저장 · TXT", export_notes(result), "PRISM_research_notes.txt", "text/plain", on_click="ignore")
            export = {"document": result["name"], "result": data}
            st.download_button("구조화 결과 저장 · JSON", json.dumps(export, ensure_ascii=False, indent=2), "PRISM_report.json", "application/json", on_click="ignore")
    with source:
        st.markdown("### 원문 근거")
        evidence = st.session_state.get("evidence", {})
        st.caption(f"PDF {evidence.get('page', '?')}쪽")
        with st.container(border=True): st.text(evidence.get("quote", "근거 보기를 눌러 주세요."))
        page = next((p for p in result["pages"] if p["page"] == evidence.get("page")), None)
        if page:
            with st.expander("해당 페이지의 추출 텍스트"):
                st.text(page["text"])
        st.caption("PDF 파일의 쪽 번호입니다. 논문에 인쇄된 쪽 번호와 다를 수 있습니다.")
    with st.expander("결과를 읽을 때 확인할 점"):
        for warning in data.get("warnings", []): st.text(warning)
        st.caption(data.get("engine", ""))


def main():
    st.set_page_config(page_title="PRISM AI", page_icon="🔺", layout="wide")
    css = Path(__file__).with_name("style.css")
    if css.exists(): st.markdown("<style>" + css.read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)
    st.markdown('<div class="prism-brand"><div class="prism-icon" role="img" aria-label="빛나는 프리즘 로고"><i></i><i></i><i></i></div><div><div class="prism-name">PRISM <span>AI</span></div><div class="prism-tagline">논문을 읽고, 연구의 핵심을 찾다.</div></div></div>', unsafe_allow_html=True)
    st.markdown('<div class="prism-flow">01 논문 넣기 <span>→</span> 02 핵심·데이터셋 읽기 <span>→</span> 03 원문 근거 확인 <span>→</span> 04 정리 저장</div>', unsafe_allow_html=True)
    url, code, config_error = settings()
    with st.expander("연결 설정 및 시험"):
        motion = st.toggle("로고 빛 효과", value=True, key="logo_glow")
        if config_error: st.info(config_error)
        else: st.caption("연결 설정이 있습니다. 실제 연결은 아래 버튼으로 확인합니다.")
        if st.button("백엔드 확인 · AI 요청 없음", disabled=bool(config_error)):
            try:
                info = api_request(url, code, "/")
                if info.get("name") != "PRISM AI": raise ValueError("PRISM 백엔드 코드가 반영되었는지 확인해 주세요.")
                st.success("PRISM 백엔드의 소개 응답을 확인했습니다.")
            except ValueError as error: st.error(str(error))
        st.caption("API 키와 접근 코드는 이 화면에 표시하거나 입력하지 않습니다.")
    if not motion: st.markdown("<style>.prism-icon{filter:none}.prism-icon::before,.prism-icon::after{display:none}</style>", unsafe_allow_html=True)
    left, right = st.columns([3, 1], gap="large")
    pages, valid, filename, document_id = [], False, "", ""
    with left:
        st.subheader("어떤 논문을 읽어볼까요?")
        uploaded = st.file_uploader("논문 PDF", type="pdf", max_upload_size=8)
        st.caption("텍스트 PDF · 최대 8MB · 스캔 문자 인식은 미지원 · 표와 수식은 추출 상태를 확인해 주세요.")
        if uploaded:
            raw, filename = uploaded.getvalue(), uploaded.name
            document_id = hashlib.sha256(raw).hexdigest()
            if st.session_state.get("document_id") != document_id:
                for key in ["result", "evidence", "page_start", "page_end"]: st.session_state.pop(key, None)
                st.session_state["document_id"] = document_id
            try:
                reader = open_pdf(raw)
                total = len(reader.pages)
                st.caption(f"총 {total}쪽 · 아래에서 선택한 범위만 분석합니다.")
                a, b = st.columns(2)
                start = a.number_input("시작 PDF 쪽", min_value=1, max_value=total, value=1, step=1, key="page_start")
                end = b.number_input("끝 PDF 쪽", min_value=1, max_value=total, value=min(total, 60), step=1, key="page_end")
                pages, skipped = extract_pages(reader, int(start), int(end))
                if skipped: st.info("텍스트가 없어 제외한 PDF 쪽: " + ", ".join(map(str, skipped)))
                st.caption(f"전송할 본문: {len(pages)}쪽 · {sum(len(p['text']) for p in pages):,}자")
                with st.expander("추출 텍스트 미리보기"):
                    st.caption("첫 페이지에서 최대 5,000자를 미리 보여줍니다. 전송 범위를 자르지는 않습니다.")
                    st.text(pages[0]["text"][:5000])
                valid = True
            except ValueError as error: st.error(str(error))
        elif st.session_state.get("document_id"):
            for key in ["result", "evidence", "document_id"]: st.session_state.pop(key, None)
        question = st.text_input("읽는 목적", DEFAULT_QUESTION, max_chars=300, key="question")
        tone = st.selectbox("정리 방식", ["간결한 연구 노트", "쉽고 친근하게", "학술적으로"], key="tone")
        request_id = signature([document_id, [p["page"] for p in pages], question.strip(), tone])
        st.caption("선택한 페이지의 텍스트가 PRISM 백엔드와 Gemini로 전송됩니다.")
        if st.button("논문 정리 시작 ↗", type="primary", disabled=not valid or bool(config_error) or not question.strip()):
            st.session_state.pop("result", None)
            try:
                with st.spinner("핵심과 데이터셋의 원문 근거를 찾고 있어요…"):
                    body = {"question": question.strip(), "tone": tone, "pages": pages}
                    result = check_result(api_request(url, code, "/ask", body), pages)
                store_result(result, pages, filename, request_id)
            except ValueError as error: st.error(str(error))
    with right:
        with st.container(border=True):
            st.markdown("### 먼저 화면을 살펴보세요")
            st.text("핵심 요약과 데이터셋을 읽고, 근거 버튼으로 원문 구절을 확인할 수 있어요.")
            if st.button("예시 화면 보기 · AI 요청 없음"):
                sample_pages = [{"page": 1, "text": SAMPLE_TEXT}]
                store_result(preview_data(), sample_pages, "기능 시험용 가상 논문", "preview", demo=True)
            st.caption("예시의 데이터와 수치는 가상입니다.")
    result = st.session_state.get("result")
    if result:
        st.divider()
        if result["demo"] or result["request_id"] == request_id:
            show_result(result)
        else:
            st.info("질문·정리 방식·페이지 범위가 바뀌었습니다. 다시 정리하면 새 결과를 볼 수 있어요.")
    st.caption("이 버전은 Gemini 기반 정보 추출입니다. 직접 학습 모델은 아직 적용하지 않았습니다. 논문과 결과는 앱 DB에 저장하지 않습니다.")


if __name__ == "__main__":
    main()
