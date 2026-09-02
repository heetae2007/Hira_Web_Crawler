import requests

# Chrome 개발자도구 Network에서
# 해당 요청의 "Request URL"을 그대로 복사
url = "https://biz.hira.or.kr/qya/bbs/selectComBbsList.ndo"

payload = """SSV:utf-8JSESSIONID=nullBIZINTERSESSION=WMONID=GzDj6WLf6tLbrowserType=ChromeosVersion=Windows 10navigatorName=ChromenavigatorVersion=152Dataset:dsParam_RowType_brdTyBltNo:STRING(256)bltNo:STRING(256)totCnt:STRING(256)currentPage:STRING(256)recordCountPerPage:STRING(256)firstIndex:STRING(256)lastIndex:STRING(256)bbsId:STRING(256)cbSearchCnd:STRING(256)edSearchWrd:STRING(256)nttId:STRING(256)atchFileId:STRING(256)codeId:STRING(256)catType01Val:STRING(256)catType02Val:STRING(256)catType03Val:STRING(256)N120020BBSMSTR_000000000675allDataset:gdsCurrentMenu_RowType_menuId:STRING(256)menuNm:STRING(256)urlDtlAddr:STRING(256)sysCd:STRING(256)scnId:STRING(256)locToDown:STRING(256)hiSysCd:STRING(256)bPopupYn:STRING(256)seAdtYn:STRING(256)formId:STRING(256)winId:STRING(256)params:STRING(256)NMP00000028질병군별포괄수가(DRG)qya_bbs::ComBbsL.xfdl홈 > 업무안내 > 자료방 > 질병군별포괄수가(DRG)bbsId=BBSMSTR_000000000675"""

response = requests.post(
    url,
    data=payload.encode("utf-8"),
    timeout=20
)

print("HTTP 상태코드:", response.status_code)
print()
print("Content-Type:", response.headers.get("Content-Type"))
print()
print("===== RESPONSE =====")
print(response.text[:10000])