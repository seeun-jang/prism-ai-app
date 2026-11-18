"""A curated, offline walkthrough. Never calls AI or overwrites an analysis."""
from pathlib import Path

import streamlit as st


@st.dialog("PRISM AI · 포스터 분석 예시", width="large")
def show_poster_demo():
    st.info("사용자가 제공한 행사 포스터와 미리 작성한 설명용 결과입니다. AI 요청은 없으며, 현재 입력과 분석 결과는 바뀌지 않습니다.")
    source, reading, resources = st.tabs(["원본 포스터", "어떻게 정리되나요?", "연결할 자료 예시"])
    with source:
        st.image(str(Path(__file__).with_name("assets") / "conference_example.png"), caption="제공된 원본 포스터")
        st.caption("포스터에 적힌 날짜·장소를 읽은 예시입니다. 현재 모집·개최 상태는 확인하지 않습니다.")
    with reading:
        st.markdown("### 사진에서 읽은 사실")
        st.table([
            {"항목": "행사", "내용": "Cloud-Barista Community 12th Conference"},
            {"항목": "주제", "내용": "멀티 클라우드가 실현하는 초연결 AI 컴퓨팅 인프라의 미래"},
            {"항목": "일시", "내용": "2026.11.18 (수) 13:30–18:00"},
            {"항목": "장소", "내용": "엘타워 오르체홀"},
            {"항목": "확인 필요", "내용": "참가비·신청 방법·세부 세션은 이 이미지에서 확인되지 않음"},
        ])
        st.markdown("### 준비 조건을 반영한 설명 예시")
        st.caption("가정한 조건: 클라우드 입문자 · 준비 기간 2주")
        st.write("첫 주에는 클라우드·멀티 클라우드·데이터센터의 기본 개념을 익혀요. 둘째 주에는 AI 모델을 여러 컴퓨터에서 학습·실행하는 이유를 살펴보고, 행사에서 물어볼 질문을 정리해요.")
        st.markdown("**찾아볼 검색어:** multi-cloud, AI infrastructure, distributed training")
        st.caption("이 준비 방향은 시연을 위해 미리 작성한 제안이며, 행사 주최 측의 교육 과정이 아닙니다.")
    with resources:
        st.caption("출처를 확인한 기초 자료 예시입니다. 실시간 검색 순위나 최신 동향 목록은 아닙니다.")
        with st.container(border=True):
            st.markdown("**도서 · The Datacenter as a Computer, 3rd edition**")
            st.caption("Luiz André Barroso · Urs Hölzle · Parthasarathy Ranganathan · 2018")
            st.write("클라우드를 뒷받침하는 데이터센터 구조를 이해할 때 연결할 수 있는 자료예요.")
            st.link_button("Google Research에서 확인 ↗", "https://research.google/pubs/the-datacenter-as-a-computer-designing-warehouse-scale-machines/")
        with st.container(border=True):
            st.markdown("**논문 · Large Scale Distributed Deep Networks**")
            st.caption("Jeffrey Dean 외 · NeurIPS 2012")
            st.write("여러 컴퓨터를 활용한 분산 딥러닝 학습의 배경을 살펴볼 수 있어요.")
            st.link_button("NeurIPS 원문 출처 ↗", "https://proceedings.neurips.cc/paper_files/paper/2012/hash/6aca97005c68f1206823815f66102863-Abstract.html")
