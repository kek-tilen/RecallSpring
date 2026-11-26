// Content of the Guide page: the recommended way to study with an assistant + RecallSpring, with short prompts.
// Prompts are learner messages to the assistant, so they are offered in English and Slovenian; the app itself stays
// English. Keep the project templates in sync with docs/claude-projects.md.
// "{assistant}" / "{Assistant}" stand for the assistant chosen in Settings → Profile (fill()).

import type { AssistantWords } from "./assistant";
import type { AssistantKey } from "./types";

export type PromptLang = "en" | "sl";

/** Puts the chosen assistant's name into a guide text. */
export function fill(text: string, a: AssistantWords): string {
  return text.replaceAll("{Assistant}", a.Name).replaceAll("{assistant}", a.name);
}

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
  /** A shortcut that exists only in Claude Desktop (its + menu). */
  claudeTip?: string;
  /** Done in a planning conversation (in Chat: "Planning (all courses)" under Study). */
  planning?: boolean;
}

export interface GuideFact {
  text: string;
  /** Shown only for these assistants (all when missing or when none is chosen). */
  only?: AssistantKey[];
}

export const SEMESTER_TEMPLATE = `This project is my semester in RecallSpring. Each chat has one job.

A planning chat (I say so in its first message) coordinates all my courses. There: create courses, import
material (import_file), and record every kolokvij and exam with its date, its scope in my own words, your
mapping of that scope to the material, and its type (set_study_target, update_study_target; analyse old papers
with record_exam_profile). Ask me for anything missing and show me the mapping before you save it. Then show
priorities across courses with get_study_plan without course_id. Do not teach or quiz in a planning chat.

Every other chat is for one course, named in its first message. Use only that course (find its course_id with
list_courses). Start with get_study_context; if the course is not set up yet, do the planning steps for it first.
Teach material I have not studied yet first, part by part in the order of the material: explain every concept
completely and concretely (what it is, how it works, an example from the material, the usual mistakes) with page
citations, never only an outline; then open_summary_form so I summarise in my own words, then 2-3 short check
questions. Never assume I studied something RecallSpring does not show as studied. Practice and
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
      "Dates, scope, material and the type of each midterm and exam let RecallSpring plan backwards from the deadline. " +
      "Give what you know; anything can be added or changed later.",
    claudeTip: "Shortcut: choose Plan semester in Claude's + menu and Claude asks you course by course.",
    planning: true,
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
        en: "Dates for [course]: 1st midterm on [date], 2nd midterm on [date], exam period from [date].",
        sl: "Datumi za [predmet]: 1. kolokvij [datum], 2. kolokvij [datum], izpitno obdobje od [datum].",
      },
      {
        en: "Scope of the 1st midterm in [course]: from [lecture or chapter] to [lecture or chapter].",
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
        note: "Photos of notes, notebook pages or solved exercises can also be dropped in Library. {Assistant} looks at them when you ask.",
      },
      {
        en: "Import the subtitles of the recorded lecture for [course]: [path to the .srt or .vtt file].",
        sl: "Uvozi podnapise posnetega predavanja za [predmet]: [pot do datoteke .srt ali .vtt].",
        note: "Also works for notebooks (.ipynb), LaTeX, code, CSV and OpenDocument files. Subtitles are cited by time, e.g. 05:00–10:00.",
      },
      {
        en: "The 1st midterm in [course] is [written or online], [minutes] minutes, [number] multiple-choice and [number] open questions, notes [allowed or not allowed].",
        sl: "1. kolokvij pri [predmet] je [pisni ali spletni], [minute] minut, [število] vprašanj izbirnega tipa in [število] odprtih, zapiski [dovoljeni ali niso dovoljeni].",
      },
      {
        en: "Here is an old midterm for [course]: [path to the file]. Analyse its style and what it emphasises, and save that.",
        sl: "Tukaj je star kolokvij za [predmet]: [pot do datoteke]. Analiziraj slog in poudarke ter to shrani.",
      },
      {
        en: "Show me how you mapped each midterm and exam to the material, then my plan for this week across all courses.",
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
      "New material comes first: {assistant} explains it part by part, each concept completely and with an example, " +
      "you summarise in your own words, then a few short check questions. Practice and simulations unlock for what you have studied.",
    prompts: [
      COURSE_CHAT_START,
      {
        en: "Explain it more simply, with an example.",
        sl: "Razloži bolj preprosto, s primerom.",
      },
      {
        en: "Look at page [number] of [file]: it is scanned. Explain the diagram on it.",
        sl: "Poglej stran [številka] v [datoteka]: je skenirana. Razloži diagram na njej.",
        note: "Claude can see scanned PDF pages, pictures on slides and pictures in Word files ([picture N] in the text); other assistants may only read the text.",
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
      "Answer in the forms {assistant} opens: they save your exact words. Simulations follow the style of your old " +
      "papers (about 75 % past-paper style, 25 % deeper).",
    prompts: [
      {
        en: "Give me 3 short questions on what I learned today.",
        sl: "Daj mi 3 kratka vprašanja o tem, kar sem se danes naučil.",
      },
      {
        en: "Run a [30]-minute simulation of the 1st midterm in the style of the old paper.",
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
    check: "Simulations shows every answer, the correct options and the assistant's feedback.",
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
    id: "interests",
    title: "Learn things outside university",
    where: "Interest chat",
    why:
      "An interest is something you learn in your free time, without an exam: data analysis, machine learning, a " +
      "language. Your courses come first: interests get the time left while every exam is on track, unless you keep " +
      "a share of each day for them or focus on one for a while.",
    claudeTip: "Shortcut: choose Add an interest in Claude's + menu.",
    planning: true,
    prompts: [
      {
        en: "Add a personal interest: [topic]. It is not for university. My goal is [goal].",
        sl: "Dodaj osebno zanimanje: [tema]. Ni za faks. Moj cilj je [cilj].",
      },
      {
        en: "This chat is for my interest [topic]. Start studying.",
        sl: "Ta klepet je za moje zanimanje [tema]. Začniva z učenjem.",
      },
      {
        en: "University comes first: plan [topic] only when my exams are on track.",
        sl: "Faks ima prednost: [tema] načrtuj samo, ko so moji izpiti na dobri poti.",
        note: "This is the default.",
      },
      {
        en: "Keep [20] % of each day for my interests.",
        sl: "Vsak dan obdrži [20] % časa za moja zanimanja.",
      },
      {
        en: "Until [date] I want to focus on [topic].",
        sl: "Do [datum] se želim posvetiti [tema].",
        note: "A focus puts it first; Today shows if an exam gets tight because of it.",
      },
      {
        en: "End the focus; university first again.",
        sl: "Končaj fokus; spet ima prednost faks.",
      },
    ],
    check: "Courses lists your interests under Interests; Today says how much time they get and why.",
  },
  {
    id: "update",
    title: "Keep the plan up to date",
    where: "Planning chat",
    why: "Tell {assistant} when something changes. Passed material moves to maintenance and new material gets priority.",
    planning: true,
    prompts: [
      {
        en: "I passed the 1st midterm in [course] with [result].",
        sl: "1. kolokvij pri [predmet] sem opravil z [rezultat].",
      },
      {
        en: "The 2nd midterm in [course] moved to [date].",
        sl: "2. kolokvij pri [predmet] je prestavljen na [datum].",
      },
      {
        en: "This week I only have [30] minutes per day.",
        sl: "Ta teden imam samo [30] minut na dan.",
      },
      {
        en: "Which midterms and exams are at risk, and by how many minutes per day?",
        sl: "Kateri kolokviji so ogroženi in za koliko minut na dan?",
      },
    ],
  },
];

export const GOOD_TO_KNOW: GuideFact[] = [
  { text: "Chat talks to ChatGPT on your own plan after you sign in (Settings → ChatGPT). Conversations are saved with the model, time and tokens of each reply. With Material you choose which of your files it may use; it cites them as S1, S2, …" },
  { text: "{Assistant} only keeps what is saved in RecallSpring. If you are unsure, ask: “Is this saved in RecallSpring?”" },
  { text: "Quizzes {assistant} writes only in the chat do not count. Ask for the RecallSpring form or a simulation." },
  { text: "Grades from {assistant} are estimates. Challenge one whenever you disagree." },
  { text: "After RecallSpring is updated, quit and reopen Claude Desktop so it loads the new connector.", only: ["claude"] },
  { text: "After RecallSpring is updated, start a new Codex session so it loads the new connector.", only: ["codex"] },
  { text: "After RecallSpring is updated, quit and reopen Antigravity so it loads the new connector.", only: ["antigravity"] },
  { text: "Your daily connector limit and study time are in Settings; every change appears in History." },
  { text: "Studied with ChatGPT before? Library → Move in brings your chats and custom instructions over; then use the “Continue from ChatGPT” prompt in a course chat." },
];
