/**
 * 등급컷 아카이브 '정보 제보' 구글폼 만들기 (Google Apps Script)
 *
 * 쓰는 법
 * 1) https://script.google.com 에서 '새 프로젝트'
 * 2) 이 파일 내용을 통째로 붙여넣고 저장
 * 3) 위쪽 함수 선택에서 createReportForm 고르고 '실행' → 권한 허용
 * 4) 아래 '실행 로그'에 나오는 '공유 주소'(forms.gle/...)를 알려주면 사이트에 제보 버튼이 생김
 *
 * 만들어지는 것: 폼 1개 + 응답이 쌓이는 스프레드시트 1개 (둘 다 내 드라이브에)
 * 이메일은 수집하지 않음 (이름도 안 물어봄)
 */

const SUBJECTS = [
  "화법과 언어", "영어II", "미적분I",
  "세포와 물질대사", "역학과 에너지", "물질과 에너지", "지구 시스템 과학",
  "기하", "경제", "윤리와 사상", "세계시민과 지리", "주제 탐구 독서",
];
const EXAMS = ["2026 2학기 중간", "2026 2학기 기말"];

function createReportForm() {
  const form = FormApp.create("오송고 등급컷 아카이브 정보 제보");
  form.setDescription(
    "오송고 2학년 시험의 등급컷·평균·점수대 인원을 알려주세요. 이름은 받지 않아요.\n" +
    "확실한 정보일수록 좋아요! 들은 곳을 같이 알려주면 얼마나 믿을지 정할 때 써요."
  );
  form.setCollectEmail(false);
  form.setAllowResponseEdits(false);
  form.setShowLinkToRespondAgain(true);       // 여러 과목을 연달아 제보할 수 있게
  form.setConfirmationMessage("고마워요! 확인해서 사이트에 반영할게요. 다른 과목도 알면 '다른 응답 제출'을 눌러 주세요.");

  // 1. 시험
  form.addMultipleChoiceItem()
    .setTitle("시험")
    .setChoiceValues(EXAMS)
    .setRequired(true);

  // 2. 과목
  form.addListItem()
    .setTitle("과목")
    .setChoiceValues(SUBJECTS)
    .setRequired(true);

  // 3. 정보 종류
  form.addCheckboxItem()
    .setTitle("어떤 정보인가요?")
    .setHelpText("해당하는 걸 모두 골라 주세요.")
    .setChoiceValues([
      "성적표의 내 점수와 석차 (예: 83.9점 52등, 동석차 2명)",
      "등급컷",
      "평균",
      "응시 인원",
      "점수대 인원 (예: 90점 이상 5명)",
      "만점자 수",
      "분포 모양 (예: 쌍봉, 선생님 말씀)",
    ])
    .showOtherOption(true);

  // 4. 내용
  form.addParagraphTextItem()
    .setTitle("내용")
    .setHelpText("예: \"83.9점 52등 (동석차 2명)\", \"2컷 67점\", \"평균 52.3\", \"80점대 11명\", \"선생님이 1컷 80 중후반이라고 하심\". 성적표의 점수와 석차 한 쌍이 석차 예상을 가장 잘 좁혀요.")
    .setRequired(true);

  // 5. 출처 (장난 제보 거르기·확정/약한 정보 구분용)
  form.addMultipleChoiceItem()
    .setTitle("어디서 들었나요?")
    .setChoiceValues(["선생님이 직접 말함", "성적표·공지", "친구에게 들음", "내 추측"])
    .setRequired(true);

  // 6. 확실한 정도
  form.addScaleItem()
    .setTitle("얼마나 확실한가요?")
    .setBounds(1, 5)
    .setLabels("잘 모르겠음", "확실함");

  // 응답을 스프레드시트로
  const sheet = SpreadsheetApp.create("오송고 등급컷 아카이브 정보 제보 (응답)");
  form.setDestination(FormApp.DestinationType.SPREADSHEET, sheet.getId());

  const shortUrl = form.shortenFormUrl(form.getPublishedUrl());
  Logger.log("공유 주소 (사이트에 넣을 것): " + shortUrl);
  Logger.log("폼 편집: " + form.getEditUrl());
  Logger.log("응답 시트: " + sheet.getUrl());
}
