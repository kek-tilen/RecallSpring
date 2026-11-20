// Content of the Guide page: the recommended way to study with Claude + RecallSpring, with short prompts.
// Prompts are learner messages to Claude, so they are offered in English and Slovenian; the app itself stays
// English. Keep the project templates in sync with docs/claude-projects.md.

export type PromptLang = "en" | "sl";

export interface GuidePrompt {
  en: string;
  sl: string;
  note?: string;
}

export interface GuideStep {
  id: string;
  title: string;
  where: string;
  why: string;
  prompts: GuidePrompt[];
  check?: string;
}

export const SEMESTER_TEMPLATE = `This project is my semester in RecallSpring. Each chat has one job.

A planning chat (I say so in its first message) coordinates all my courses. There: create courses, import
material (import_file), and record every kolokvij and exam with its date, its scope in my own words, your
mapping of that scope to the material, and its type (set_study_target, update_study_target; analyse old papers
with record_exam_profile). Ask me for anything missing and show me the mapping before you save it. Then show
priorities across courses with get_study_plan without course_id. Do not teach or quiz in a planning chat.

Every other chat is for one course, named in its first message. Use only that course (find its course_id with
list_courses). Start with get_study_context; if the course is not set up yet, do the planning steps for it first.
Teach material I have not studied yet first: a few pages at a time in the order of the material, with page
citations, then open_summary_form so I summarise in my own words, then 2-3 short check questions. Practice and
simulations only for studied material (create_quiz in the style of the exam profile, about 75 % past-paper style
and 25 % deeper, then open_quiz). Grade open answers with record_assessments and tell me the next review dates.

Save everything through RecallSpring, never only in the chat. Answer in the language I write in.`;

export const COURSE_CHAT_START: GuidePrompt = {
  en: "This chat is for [course]. Start studying.",
  sl: "Ta klepet je za [predmet]. Začniva z učenjem.",
};

export const PLANNING_CHAT_START: GuidePrompt = {
  en: "This is my planning chat. Let's set up my semester in RecallSpring.",
  sl: "To je klepet za načrtovanje. Nastaviva moj semester v RecallSpringu.",
};

export const STEPS: GuideStep[] = [
  {
    id: "plan",
    title: "Plan the semester first",
    where: "Planning chat",
    why:
      "Dates, scope, material and the type of each kolokvij let RecallSpring plan backwards from the deadline. " +
      "Give what you know; anything can be added or changed later. Shortcut: choose Plan semester in Claude's + menu " +
      "and Claude asks you course by course.",
    prompts: [
      PLANNING_CHAT_START,
      {
        en: "My courses this semester are [course], [course] and [course]. Create them in RecallSpring.",
        sl: "Moji predmeti v tem semestru so [predmet], [predmet] in [predmet]. Ustvari jih v RecallSpringu.",
      },
      {
        en: "File [course] and [course] under [university], [faculty], [semester].",
        sl: "Predmeta [predmet] in [predmet] razvrsti pod [univerza], [fakulteta], [semester].",
        note: "Courses then appear grouped by semester; archive a semester when it ends.",
      },
      {
        en: "Dates for [course]: 1st kolokvij on [date], 2nd kolokvij on [date], exam period from [date].",
        sl: "Datumi za [predmet]: 1. kolokvij [datum], 2. kolokvij [datum], izpitno obdobje od [datum].",
      },
      {
        en: "Scope of the 1st kolokvij in [course]: from [lecture or chapter] to [lecture or chapter].",
        sl: "Obseg 1. kolokvija pri [predmet]: od [predavanje ali poglavje] do [predavanje ali poglavje].",
      },
      {
        en: "Import my material for [course]: [path to the file].",
        sl: "Uvozi gradivo za [predmet]: [pot do datoteke].",
        note: "Files in Documents, Downloads or Desktop go straight to RecallSpring, not through the chat. You can also drop them in Library.",
      },
      {
        en: "Import my handwritten notes for [course] as my notes: [path to the photo].",
        sl: "Uvozi moje zapiske za [predmet] kot moje zapiske: [pot do fotografije].",
        note: "Photos of notes, notebook pages or solved exercises can also be dropped in Library. Claude looks at them when you ask.",
      },
      {
        en: "Import the subtitles of the recorded lecture for [course]: [path to the .srt or .vtt file].",
        sl: "Uvozi podnapise posnetega predavanja za [predmet]: [pot do datoteke .srt ali .vtt].",
        note: "Also works for notebooks (.ipynb), LaTeX, code, CSV and OpenDocument files. Subtitles are cited by time, e.g. 05:00–10:00.",
      },
      {
        en: "The 1st kolokvij in [course] is [written or online], [minutes] minutes, [number] multiple-choice and [number] open questions, notes [allowed or not allowed].",
        sl: "1. kolokvij pri [predmet] je [pisni ali spletni], [minute] minut, [število] vprašanj izbirnega tipa in [število] odprtih, zapiski [dovoljeni ali niso dovoljeni].",
      },
      {
        en: "Here is an old kolokvij for [course]: [path to the file]. Analyse its style and what it emphasises, and save that.",
        sl: "Tukaj je star kolokvij za [predmet]: [pot do datoteke]. Analiziraj slog in poudarke ter to shrani.",
      },
      {
        en: "Show me how you mapped each kolokvij to the material, then my plan for this week across all courses.",
        sl: "Pokaži, kako si vsak kolokvij povezal z gradivom, in nato moj načrt za ta teden za vse predmete.",
      },
    ],
    check:
      "Exams shows every date on a timeline (drag one to move it) and downloads them to your calendar; Courses groups " +
      "your courses by semester.",
  },
  {
    id: "learn",
    title: "Learn new material",
    where: "Course chat",
    why:
      "New material comes first: Claude explains a few pages at a time, you summarise in your own words, then a " +
      "few short check questions. Practice and simulations unlock for what you have studied.",
    prompts: [
      COURSE_CHAT_START,
      {
        en: "Explain it more simply, with an example.",
        sl: "Razloži bolj preprosto, s primerom.",
      },
      {
        en: "Look at page [number] of [file]: it is scanned. Explain the diagram on it.",
        sl: "Poglej stran [številka] v [datoteka]: je skenirana. Razloži diagram na njej.",
        note: "Claude can see scanned PDF pages, pictures on slides and pictures in Word files ([picture N] in the text).",
      },
      {
        en: "I already know [topic] from the lectures. Mark it as known.",
        sl: "[tema] že poznam s predavanj. Označi jo kot znano.",
      },
      {
        en: "I'm done with this part. Open the summary form.",
        sl: "S tem delom sem končal. Odpri obrazec za povzetek.",
      },
      {
        en: "Before we start, give me a short diagnostic test on [topic] to see what I already know.",
        sl: "Preden začneva, mi daj kratek diagnostični test iz [tema], da vidiva, kaj že znam.",
        note: "Optional. A diagnostic test never changes your review schedule.",
      },
    ],
  },
  {
    id: "practise",
    title: "Practise and simulate",
    where: "Course chat",
    why:
      "Answer in the forms Claude opens: they save your exact words. Simulations follow the style of your old " +
      "papers (about 75 % past-paper style, 25 % deeper).",
    prompts: [
      {
        en: "Give me 3 short questions on what I learned today.",
        sl: "Daj mi 3 kratka vprašanja o tem, kar sem se danes naučil.",
      },
      {
        en: "Run a [30]-minute simulation of the 1st kolokvij in the style of the old paper.",
        sl: "Pripravi [30]-minutno simulacijo 1. kolokvija v slogu starega kolokvija.",
      },
      {
        en: "I solved the simulation [title] in RecallSpring. Grade my open answers.",
        sl: "Simulacijo [naslov] sem rešil v RecallSpringu. Oceni moje odprte odgovore.",
        note: "Open simulations can be answered in Simulations too; the page gives you this message with the ID to copy.",
      },
      {
        en: "Grade my simulation and tell me what to repeat.",
        sl: "Oceni mojo simulacijo in povej, kaj naj ponovim.",
      },
      {
        en: "I think this grade is wrong because [reason]. Please check it again.",
        sl: "Mislim, da ta ocena ni pravilna, ker [razlog]. Preveri jo še enkrat.",
      },
    ],
    check: "Simulations shows every answer, the correct options and Claude's feedback.",
  },
  {
    id: "review",
    title: "Review a little every day",
    where: "Any course chat",
    why: "RecallSpring schedules reviews from your graded answers. Short daily reviews keep earlier material from fading.",
    prompts: [
      {
        en: "What is due for review today? Ask me one question at a time.",
        sl: "Kaj moram danes ponoviti? Sprašuj me po eno vprašanje.",
      },
      {
        en: "I only have [20] minutes today. What matters most?",
        sl: "Danes imam samo [20] minut. Kaj je najpomembnejše?",
      },
    ],
    check: "Review lists what is due today and next; you can snooze a review there.",
  },
  {
    id: "update",
    title: "Keep the plan up to date",
    where: "Planning chat",
    why: "Tell Claude when something changes. Passed material moves to maintenance and new material gets priority.",
    prompts: [
      {
        en: "I passed the 1st kolokvij in [course] with [result].",
        sl: "1. kolokvij pri [predmet] sem opravil z [rezultat].",
      },
      {
        en: "The 2nd kolokvij in [course] moved to [date].",
        sl: "2. kolokvij pri [predmet] je prestavljen na [datum].",
      },
      {
        en: "This week I only have [30] minutes per day.",
        sl: "Ta teden imam samo [30] minut na dan.",
      },
      {
        en: "Which kolokviji are at risk, and by how many minutes per day?",
        sl: "Kateri kolokviji so ogroženi in za koliko minut na dan?",
      },
    ],
  },
];

export const GOOD_TO_KNOW: string[] = [
  "Claude only keeps what is saved in RecallSpring. If you are unsure, ask: “Is this saved in RecallSpring?”",
  "Quizzes Claude writes only in the chat do not count. Ask for the RecallSpring form or a simulation.",
  "Grades from Claude are estimates. Challenge one whenever you disagree.",
  "After RecallSpring is updated, quit and reopen Claude Desktop so it loads the new connector.",
  "Your daily connector limit and study time are in Settings; every change appears in History.",
];
