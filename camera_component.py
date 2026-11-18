"""Opt-in local video preview and bounded frame capture for Streamlit 1.66+."""
import streamlit as st

HTML = """<section class="camera"><video autoplay playsinline muted aria-label="실시간 카메라 미리보기"></video>
<div class="actions"><button id="start">카메라 켜기</button><button id="capture" disabled>지금 화면 분석</button>
<button id="auto" disabled>15초마다 자동 분석 · 최대 3회</button><button id="stop" disabled>카메라 끄기</button></div>
<p role="status" aria-live="polite">카메라는 버튼을 누를 때만 켜집니다. 화면은 촬영·자동 분석을 선택할 때만 전송됩니다.</p></section>"""
CSS = """.camera{font:14px system-ui,sans-serif;color:#24252d}.camera video{width:100%;max-height:430px;
background:#f6f6f8;object-fit:contain;border-radius:10px;min-height:180px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
button{border:1px solid #dfe0e6;border-radius:8px;padding:10px 13px;min-height:44px;background:white;color:#3e404a;cursor:pointer}
#capture{background:#7053a1;color:white}button:disabled{background:#f4f4f6;color:#999ba5;cursor:default}
p{line-height:1.65;color:#62646e;margin:10px 0}button:focus-visible{outline:3px solid #bca2da;outline-offset:2px}"""
JS = r"""
export default function(component) {
  const root = component.parentElement.querySelector('.camera');
  if (!root) return;
  let s = root.prismCamera;
  if (!s) {
    s = root.prismCamera = {stream:null, auto:false, count:0, busy:false, pending:null, lastPixels:null};
    s.video = root.querySelector('video');
    s.status = root.querySelector('[role="status"]');
    s.start = root.querySelector('#start'); s.capture = root.querySelector('#capture');
    s.autoButton = root.querySelector('#auto'); s.stopButton = root.querySelector('#stop');
    const message = text => { s.status.textContent = text; };
    s.update = () => {
      const live = Boolean(s.stream);
      s.start.disabled = live; s.stopButton.disabled = !live;
      s.capture.disabled = !live || s.busy || !s.enabled;
      s.autoButton.disabled = !live || !s.enabled;
      s.autoButton.textContent = s.auto ? '자동 분석 중지' : '15초마다 자동 분석 · 최대 3회';
    };
    s.stop = () => {
      s.auto = false;
      if (s.stream) s.stream.getTracks().forEach(t => t.stop());
      s.stream = null; s.video.srcObject = null; s.update();
      message('카메라를 껐습니다. 분석 결과는 유지됩니다.');
    };
    const capture = automatic => {
      if (!s.stream || !s.video.videoWidth || s.busy || !s.enabled) return;
      const canvas = document.createElement('canvas');
      const scale = Math.min(1, 1600 / Math.max(s.video.videoWidth, s.video.videoHeight));
      canvas.width = Math.round(s.video.videoWidth*scale); canvas.height = Math.round(s.video.videoHeight*scale);
      canvas.getContext('2d').drawImage(s.video, 0, 0, canvas.width, canvas.height);
      const tiny = document.createElement('canvas'); tiny.width=24; tiny.height=24;
      const ctx=tiny.getContext('2d'); ctx.drawImage(canvas,0,0,24,24);
      const pixels=ctx.getImageData(0,0,24,24).data;
      if (automatic && s.lastPixels) {
        let difference=0;
        for(let i=0;i<pixels.length;i+=4) difference+=Math.abs(pixels[i]-s.lastPixels[i])+Math.abs(pixels[i+1]-s.lastPixels[i+1])+Math.abs(pixels[i+2]-s.lastPixels[i+2]);
        if(difference/(24*24*3)<5) { message('비슷한 화면이라 재전송을 건너뛰었습니다. 새 포스터를 비추면 분석합니다.'); s.next=Date.now()+15000; return; }
      }
      const b64=canvas.toDataURL('image/jpeg',0.85).split(',')[1];
      if(b64.length>2800000) { message('화면이 너무 큽니다. 포스터의 필요한 부분을 가까이 비춰 주세요.'); return; }
      s.lastPixels = new Uint8ClampedArray(pixels);
      s.pending = `${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
      s.busy = true; if(automatic) s.count++;
      message(automatic ? `자동 분석 ${s.count}/3 · 결과를 기다리는 중입니다.` : '촬영한 화면을 분석 중입니다.');
      s.update();
      s.component.setTriggerValue('capture', {id:s.pending,image_b64:b64,automatic});
    };
    s.start.onclick = async () => {
      if(!navigator.mediaDevices?.getUserMedia) { message('이 브라우저는 카메라를 지원하지 않습니다. HTTPS 주소나 사진 업로드를 이용해 주세요.'); return; }
      try {
        s.stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:'environment'},width:{ideal:1920},height:{ideal:1080}}});
        s.video.srcObject=s.stream; await s.video.play(); s.update();
        message(s.enabled ? '미리보기 중입니다. 지금 화면 분석 또는 자동 분석을 선택하세요.' : '미리보기 중입니다. 분석하려면 앱 연결 설정을 완료해 주세요.');
      } catch(error) { s.stop(); message(error.name==='NotAllowedError'?'카메라 권한이 차단되었습니다. 주소창 권한 설정을 확인하거나 사진을 업로드해 주세요.':'사용 가능한 카메라를 찾지 못했습니다. 사진 업로드를 이용해 주세요.'); }
    };
    s.capture.onclick=()=>capture(false);
    s.autoButton.onclick=()=>{s.auto=!s.auto;s.count=0;s.lastPixels=null;s.next=Date.now();s.update(); if(!s.auto) message('자동 분석을 중지했습니다. 미리보기는 유지됩니다.');};
    s.stopButton.onclick=s.stop;
    s.visibility=()=>{if(document.hidden)s.stop();}; document.addEventListener('visibilitychange',s.visibility);
    s.timer=setInterval(()=>{
      if(!root.isConnected) {s.stop();clearInterval(s.timer);document.removeEventListener('visibilitychange',s.visibility);return;}
      if(s.stream && root.getBoundingClientRect().height===0) {s.stop();return;}
      if(s.auto && s.count>=3 && !s.busy){s.auto=false;s.update();message('자동 분석 3회를 마쳤습니다. 필요하면 다시 시작할 수 있어요.');return;}
      if(s.auto && !s.busy && Date.now()>=s.next) capture(true);
    },1000);
  }
  s.component=component; s.enabled=Boolean(component.data?.enabled);
  if(s.pending && component.data?.ack===s.pending) { s.busy=false;s.next=Date.now()+15000; }
  s.update();
  return () => { queueMicrotask(()=>{if(!root.isConnected){s.stop();clearInterval(s.timer);document.removeEventListener('visibilitychange',s.visibility);}}); };
}
"""

_camera = st.components.v2.component("prism_live_camera", html=HTML, css=CSS, js=JS)


def live_camera(enabled, ack):
    result = _camera(data={"enabled": enabled, "ack": ack}, key="prism_live_capture",
                     on_capture_change=lambda: None)
    return result.capture
