# Tasker XML Task Definitions — LifeData V4

> **Import Instructions:** Each task below is wrapped in its own `<TaskerData>` block.
> To import: copy the XML block into a `.xml` file on your phone, then in Tasker:
> **Menu (three dots) > Import > select the file**.
>
> **Notes:**
> - Task IDs may conflict with existing tasks. Tasker will auto-assign new IDs on import.
> - Profiles must be created manually in the Tasker UI (instructions included per profile).
> - All file paths assume the standard LifeData spool structure: `Documents/LifeData/spool/<module>/`
> - Verify `%TIMES`, `%TIME`, and `%TIMEZONE` resolve correctly on your device.
> - JavaScriptlet actions require Tasker's JavaScript engine to be enabled.

---

## Table of Contents

1. [Task 310: Digit_Span](#task-310-digit_span)
2. [Task 330: Typing_Speed_Test](#task-330-typing_speed_test)
3. [Task 340: Cognitive_Battery](#task-340-cognitive_battery)
4. [Task 350: IChing_Cast](#task-350-iching_cast)
5. [Task 351: RNG_Sample](#task-351-rng_sample)
6. [Task 352: IChing_Auto](#task-352-iching_auto)
7. [Task 360: Log_Unlock_Latency](#task-360-log_unlock_latency)
8. [Task 370: Log_Steps_Hourly](#task-370-log_steps_hourly)
9. [Task 380: Dream_Quick_Log](#task-380-dream_quick_log)
10. [Task 381: Dream_Structured_Recall](#task-381-dream_structured_recall)
11. [Profiles](#profiles)

---

## Task 310: Digit_Span

**Module:** Cognition (NU)
**Purpose:** Adaptive forward digit span test for working memory capacity.
**Duration:** ~45-90 seconds
**Trigger:** Widget / manual

```xml
<TaskerData sr="" dession="all" tv="6.3.14">
	<Task sr="task310">
		<cdate>1711900000000</cdate>
		<edate>1711900000000</edate>
		<id>310</id>
		<nme>Digit_Span</nme>
		<pri>100</pri>

		<!-- A1. Variable Set: %LD_DS_LENGTH = 3 -->
		<Action sr="act0" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_DS_LENGTH</Str>
			<Str sr="arg1" ve="3">3</Str>
			<Int sr="arg2" val="0"/>
		</Action>

		<!-- A2. Variable Set: %LD_DS_CORRECT_STREAK = 0 -->
		<Action sr="act1" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_DS_CORRECT_STREAK</Str>
			<Str sr="arg1" ve="3">0</Str>
			<Int sr="arg2" val="0"/>
		</Action>

		<!-- A3. Variable Set: %LD_DS_MAX_SPAN = 0 -->
		<Action sr="act2" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_DS_MAX_SPAN</Str>
			<Str sr="arg1" ve="3">0</Str>
			<Int sr="arg2" val="0"/>
		</Action>

		<!-- A4. Variable Set: %LD_DS_RESULTS = "" -->
		<Action sr="act3" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_DS_RESULTS</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="0"/>
		</Action>

		<!-- A5. Variable Set: %LD_DS_TRIAL = 0 -->
		<Action sr="act4" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_DS_TRIAL</Str>
			<Str sr="arg1" ve="3">0</Str>
			<Int sr="arg2" val="0"/>
		</Action>

		<!-- A6. LABEL: LOOP_START -->
		<!-- A7. Variable Add: %LD_DS_TRIAL + 1 -->
		<Action sr="act5" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_DS_TRIAL</Str>
			<Str sr="arg1" ve="3">%LD_DS_TRIAL + 1</Str>
			<Int sr="arg2" val="1"/>
		</Action>

		<!-- A8. JavaScriptlet: Generate random digit sequence -->
		<Action sr="act6" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var len = parseInt(global('LD_DS_LENGTH'));
var seq = [];
for (var i = 0; i &lt; len; i++) {
  var d;
  do { d = Math.floor(Math.random() * 10); }
  while (seq.length > 0 &amp;&amp; d === seq[seq.length - 1]);
  seq.push(d);
}
setGlobal('LD_DS_SEQUENCE', seq.join(''));
setGlobal('LD_DS_DISPLAY', seq.join('  '));
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="10"/>
		</Action>

		<!-- A9. Flash: Show digit sequence (long duration) -->
		<Action sr="act7" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">%LD_DS_DISPLAY</Str>
			<Int sr="arg1" val="1"/>
		</Action>

		<!-- A10. Wait: Display time = length * 800ms (use 3 sec as reasonable default) -->
		<Action sr="act8" ve="7">
			<code>30</code>
			<Int sr="arg0" val="0"/>
			<Int sr="arg1" val="0"/>
			<Int sr="arg2" val="3"/>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A11. Wait: 500ms retention interval -->
		<Action sr="act9" ve="7">
			<code>30</code>
			<Int sr="arg0" val="0"/>
			<Int sr="arg1" val="0"/>
			<Int sr="arg2" val="0"/>
			<Int sr="arg3" val="500"/>
		</Action>

		<!-- A12. Variable Query: "Enter the digits" -->
		<Action sr="act10" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_DS_RESPONSE</Str>
			<Str sr="arg1" ve="3">Enter the digits</Str>
			<Str sr="arg2" ve="3"></Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A13. JavaScriptlet: Check response and update staircase -->
		<Action sr="act11" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var response = global('LD_DS_RESPONSE');
var sequence = global('LD_DS_SEQUENCE');
var length = parseInt(global('LD_DS_LENGTH'));
var streak = parseInt(global('LD_DS_CORRECT_STREAK'));
var maxSpan = parseInt(global('LD_DS_MAX_SPAN'));
var results = global('LD_DS_RESULTS');
var correct = (response === sequence) ? 1 : 0;

results = results + (results ? '|' : '') + length + ':' + sequence + ':' + response + ':' + correct;
setGlobal('LD_DS_RESULTS', results);

if (correct) {
  streak += 1;
  if (streak >= 2) {
    length += 1;
    streak = 0;
  }
} else {
  maxSpan = Math.max(maxSpan, length - 1);
  length -= 1;
  streak = 0;
  if (length &lt; 2) {
    setGlobal('LD_DS_STOP', '1');
  }
}
setGlobal('LD_DS_LENGTH', length);
setGlobal('LD_DS_CORRECT_STREAK', streak);
setGlobal('LD_DS_MAX_SPAN', maxSpan);
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="10"/>
		</Action>

		<!-- A14. If: %LD_DS_STOP == 1 -> Goto END -->
		<Action sr="act12" ve="7">
			<code>37</code>
			<Str sr="arg0" ve="3">%LD_DS_STOP</Str>
			<Int sr="arg1" val="0"/>
			<Str sr="arg2" ve="3">1</Str>
		</Action>

		<!-- A15. Goto: END (act17) -->
		<Action sr="act13" ve="7">
			<code>135</code>
			<Int sr="arg0" val="17"/>
		</Action>

		<!-- A16. End If -->
		<Action sr="act14" ve="7">
			<code>38</code>
		</Action>

		<!-- A17. If: %LD_DS_TRIAL < 8 AND %LD_DS_LENGTH <= 12 -> loop -->
		<Action sr="act15" ve="7">
			<code>37</code>
			<Str sr="arg0" ve="3">%LD_DS_TRIAL</Str>
			<Int sr="arg1" val="7"/>
			<Str sr="arg2" ve="3">8</Str>
		</Action>

		<!-- A18. Goto: LOOP_START (act5) -->
		<Action sr="act16" ve="7">
			<code>135</code>
			<Int sr="arg0" val="5"/>
		</Action>

		<!-- A19. End If -->
		<Action sr="act17" ve="7">
			<code>38</code>
		</Action>

		<!-- A20. LABEL: END -->
		<!-- A21. JavaScriptlet: Finalize max span -->
		<Action sr="act18" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var maxSpan = parseInt(global('LD_DS_MAX_SPAN'));
var length = parseInt(global('LD_DS_LENGTH'));
setGlobal('LD_DS_MAX_SPAN', Math.max(maxSpan, length));
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="5"/>
		</Action>

		<!-- A22. Write File: Save results -->
		<Action sr="act19" ve="7">
			<code>410</code>
			<Str sr="arg0" ve="3">Documents/LifeData/spool/cognition/digit_span_%TIMES.csv</Str>
			<Str sr="arg1" ve="3">%TIMES,%TIME,%TIMEZONE,%LD_DS_MAX_SPAN,%LD_DS_RESULTS</Str>
			<Int sr="arg2" val="0"/>
			<Int sr="arg3" val="1"/>
		</Action>

		<!-- A23. Flash: Result -->
		<Action sr="act20" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Digit span: %LD_DS_MAX_SPAN</Str>
			<Int sr="arg1" val="1"/>
		</Action>
	</Task>
</TaskerData>
```

**CSV Format:** `epoch,time,timezone,max_span,trial_results`
Where `trial_results` = pipe-delimited `length:sequence:response:correct` tuples.

---

## Task 330: Typing_Speed_Test

**Module:** Cognition (NU)
**Purpose:** 15-second typing speed and accuracy test (psychomotor probe).
**Duration:** ~15 seconds
**Trigger:** Widget / manual

```xml
<TaskerData sr="" dession="all" tv="6.3.14">
	<Task sr="task330">
		<cdate>1711900000000</cdate>
		<edate>1711900000000</edate>
		<id>330</id>
		<nme>Typing_Speed_Test</nme>
		<pri>100</pri>

		<!-- A1. JavaScriptlet: Select random pangram prompt -->
		<Action sr="act0" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var prompts = [
  "the quick brown fox jumps over the lazy dog",
  "pack my box with five dozen liquor jugs",
  "how vexingly quick daft zebras jump",
  "the five boxing wizards jump quickly",
  "bright vixens jump dozy fowl quack",
  "jackdaws love my big sphinx of quartz",
  "we promptly judged antique ivory buckles",
  "crazy frederick bought many very exquisite opal jewels",
  "sixty zippers were quickly picked from the woven jute bag",
  "a quick movement of the enemy will jeopardize six gunboats"
];
var idx = Math.floor(Math.random() * prompts.length);
setGlobal('LD_TYPE_PROMPT', prompts[idx]);
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="5"/>
		</Action>

		<!-- A2. Flash: Instructions -->
		<Action sr="act1" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Type this as fast and accurately as you can:</Str>
			<Int sr="arg1" val="0"/>
		</Action>

		<!-- A3. Variable Set: %LD_TYPE_START = %TIMEMS -->
		<Action sr="act2" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_TYPE_START</Str>
			<Str sr="arg1" ve="3">%TIMEMS</Str>
			<Int sr="arg2" val="0"/>
		</Action>

		<!-- A4. Variable Query: Show prompt, capture typed response -->
		<Action sr="act3" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_TYPE_RESPONSE</Str>
			<Str sr="arg1" ve="3">%LD_TYPE_PROMPT</Str>
			<Str sr="arg2" ve="3"></Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A5. Variable Set: %LD_TYPE_END = %TIMEMS -->
		<Action sr="act4" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_TYPE_END</Str>
			<Str sr="arg1" ve="3">%TIMEMS</Str>
			<Int sr="arg2" val="0"/>
		</Action>

		<!-- A6. Variable Set: Duration in seconds (math) -->
		<Action sr="act5" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_TYPE_DUR_SEC</Str>
			<Str sr="arg1" ve="3">(%LD_TYPE_END - %LD_TYPE_START) / 1000</Str>
			<Int sr="arg2" val="1"/>
		</Action>

		<!-- A7. JavaScriptlet: Compute WPM, accuracy, errors -->
		<Action sr="act6" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var prompt = global('LD_TYPE_PROMPT');
var response = global('LD_TYPE_RESPONSE');
var dur = parseFloat(global('LD_TYPE_DUR_SEC'));

var words = response.trim().split(/\s+/).length;
var wpm = Math.round((words / dur) * 60);

var correct = 0;
var len = Math.min(prompt.length, response.length);
for (var i = 0; i &lt; len; i++) {
  if (prompt[i] === response[i]) correct++;
}
var accuracy = Math.round((correct / prompt.length) * 100);
var errors = prompt.length - correct;

setGlobal('LD_TYPE_WPM', wpm);
setGlobal('LD_TYPE_ACC', accuracy);
setGlobal('LD_TYPE_ERRORS', errors);
setGlobal('LD_TYPE_CHARS', response.length);
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="10"/>
		</Action>

		<!-- A8. Write File: Save results -->
		<Action sr="act7" ve="7">
			<code>410</code>
			<Str sr="arg0" ve="3">Documents/LifeData/spool/cognition/typing_%TIMES.csv</Str>
			<Str sr="arg1" ve="3">%TIMES,%TIME,%TIMEZONE,%LD_TYPE_WPM,%LD_TYPE_ACC,%LD_TYPE_ERRORS,%LD_TYPE_CHARS,%LD_TYPE_DUR_SEC</Str>
			<Int sr="arg2" val="0"/>
			<Int sr="arg3" val="1"/>
		</Action>

		<!-- A9. Flash: Result -->
		<Action sr="act8" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Typing: %LD_TYPE_WPM wpm, %LD_TYPE_ACC% accuracy</Str>
			<Int sr="arg1" val="1"/>
		</Action>
	</Task>
</TaskerData>
```

**CSV Format:** `epoch,time,timezone,wpm,accuracy_pct,errors,chars,duration_sec`

---

## Task 340: Cognitive_Battery

**Module:** Cognition (NU)
**Purpose:** Chains Simple_RT + Digit_Span + Time_Production + Typing_Speed into a single ~90-second session.
**Duration:** ~90 seconds
**Trigger:** Widget / manual
**Requires:** Tasks 300, 310, 320, 330 must exist.

```xml
<TaskerData sr="" dession="all" tv="6.3.14">
	<Task sr="task340">
		<cdate>1711900000000</cdate>
		<edate>1711900000000</edate>
		<id>340</id>
		<nme>Cognitive_Battery</nme>
		<pri>100</pri>

		<!-- A1. Flash: Battery starting -->
		<Action sr="act0" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Cognitive Battery starting... (~90 sec)</Str>
			<Int sr="arg1" val="0"/>
		</Action>

		<!-- A2. Wait 1 second -->
		<Action sr="act1" ve="7">
			<code>30</code>
			<Int sr="arg0" val="0"/>
			<Int sr="arg1" val="0"/>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A3. Perform Task: Simple_RT -->
		<Action sr="act2" ve="7">
			<code>130</code>
			<Str sr="arg0" ve="3">Simple_RT</Str>
			<Int sr="arg1" val="10"/>
			<Str sr="arg2" ve="3"></Str>
			<Str sr="arg3" ve="3"></Str>
		</Action>

		<!-- A4. Wait 2 seconds between tests -->
		<Action sr="act3" ve="7">
			<code>30</code>
			<Int sr="arg0" val="0"/>
			<Int sr="arg1" val="0"/>
			<Int sr="arg2" val="2"/>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A5. Flash: Next test -->
		<Action sr="act4" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Next: Digit Span</Str>
			<Int sr="arg1" val="0"/>
		</Action>

		<!-- A6. Perform Task: Digit_Span -->
		<Action sr="act5" ve="7">
			<code>130</code>
			<Str sr="arg0" ve="3">Digit_Span</Str>
			<Int sr="arg1" val="10"/>
			<Str sr="arg2" ve="3"></Str>
			<Str sr="arg3" ve="3"></Str>
		</Action>

		<!-- A7. Wait 2 seconds -->
		<Action sr="act6" ve="7">
			<code>30</code>
			<Int sr="arg0" val="0"/>
			<Int sr="arg1" val="0"/>
			<Int sr="arg2" val="2"/>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A8. Flash: Next test -->
		<Action sr="act7" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Next: Time Production</Str>
			<Int sr="arg1" val="0"/>
		</Action>

		<!-- A9. Perform Task: Time_Production -->
		<Action sr="act8" ve="7">
			<code>130</code>
			<Str sr="arg0" ve="3">Time_Production</Str>
			<Int sr="arg1" val="10"/>
			<Str sr="arg2" ve="3"></Str>
			<Str sr="arg3" ve="3"></Str>
		</Action>

		<!-- A10. Wait 2 seconds -->
		<Action sr="act9" ve="7">
			<code>30</code>
			<Int sr="arg0" val="0"/>
			<Int sr="arg1" val="0"/>
			<Int sr="arg2" val="2"/>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A11. Flash: Next test -->
		<Action sr="act10" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Next: Typing Speed</Str>
			<Int sr="arg1" val="0"/>
		</Action>

		<!-- A12. Perform Task: Typing_Speed_Test -->
		<Action sr="act11" ve="7">
			<code>130</code>
			<Str sr="arg0" ve="3">Typing_Speed_Test</Str>
			<Int sr="arg1" val="10"/>
			<Str sr="arg2" ve="3"></Str>
			<Str sr="arg3" ve="3"></Str>
		</Action>

		<!-- A13. Flash: Battery complete -->
		<Action sr="act12" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Cognitive Battery complete!</Str>
			<Int sr="arg1" val="1"/>
		</Action>
	</Task>
</TaskerData>
```

---

## Task 350: IChing_Cast

**Module:** Oracle (XI)
**Purpose:** Manual I Ching casting with method selection (Three Coins, Yarrow Stalks, or RNG).
**Duration:** ~10 seconds
**Trigger:** Widget / manual

```xml
<TaskerData sr="" dession="all" tv="6.3.14">
	<Task sr="task350">
		<cdate>1711900000000</cdate>
		<edate>1711900000000</edate>
		<id>350</id>
		<nme>IChing_Cast</nme>
		<pri>100</pri>

		<!-- A1. Variable Query: Select casting method -->
		<Action sr="act0" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_ICHING_METHOD</Str>
			<Str sr="arg1" ve="3">I Ching - Method?
Three Coins / Yarrow Stalks / Random</Str>
			<Str sr="arg2" ve="3">Three Coins</Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A2. Variable Query: Question (optional) -->
		<Action sr="act1" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_ICHING_QUESTION</Str>
			<Str sr="arg1" ve="3">What is your question? (optional)</Str>
			<Str sr="arg2" ve="3">no_question</Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A3. JavaScriptlet: Generate hexagram -->
		<Action sr="act2" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var method = global('LD_ICHING_METHOD').toLowerCase();
var lines = [];

function coinLine() {
  var sum = 0;
  for (var c = 0; c &lt; 3; c++) {
    sum += Math.random() &lt; 0.5 ? 3 : 2;
  }
  return sum;
}

function yarrowLine() {
  var r = Math.random();
  if (r &lt; 0.0625) return 6;
  if (r &lt; 0.375) return 7;
  if (r &lt; 0.8125) return 8;
  return 9;
}

for (var i = 0; i &lt; 6; i++) {
  if (method.indexOf('yarrow') >= 0) lines.push(yarrowLine());
  else lines.push(coinLine());
}

var primary = 0;
var resulting = 0;
var changing = [];
for (var i = 5; i >= 0; i--) {
  var yang = (lines[i] === 7 || lines[i] === 9) ? 1 : 0;
  primary = (primary &lt;&lt; 1) | yang;
  var res_yang = yang;
  if (lines[i] === 6) { res_yang = 1; changing.push(i + 1); }
  if (lines[i] === 9) { res_yang = 0; changing.push(i + 1); }
  resulting = (resulting &lt;&lt; 1) | res_yang;
}

var KING_WEN = {
  0:2,1:23,2:8,3:20,4:16,5:35,6:45,7:12,
  8:15,9:52,10:39,11:53,12:62,13:56,14:31,15:33,
  16:7,17:4,18:29,19:59,20:40,21:64,22:47,23:6,
  24:46,25:18,26:48,27:57,28:32,29:50,30:28,31:44,
  32:24,33:27,34:3,35:42,36:51,37:21,38:17,39:25,
  40:36,41:22,42:63,43:37,44:55,45:30,46:49,47:13,
  48:19,49:41,50:60,51:61,52:54,53:38,54:58,55:10,
  56:11,57:26,58:5,59:9,60:34,61:14,62:43,63:1
};

var NAMES = {
  1:'Force (Qian)',2:'Field (Kun)',3:'Sprouting (Zhun)',4:'Enveloping (Meng)',
  5:'Attending (Xu)',6:'Conflict (Song)',7:'Leading (Shi)',8:'Grouping (Bi)',
  9:'Small Accumulating',10:'Treading (Lu)',11:'Pervading (Tai)',12:'Obstruction (Pi)',
  13:'Concording People',14:'Great Possessing',15:'Humbling (Qian)',16:'Providing-For (Yu)',
  17:'Following (Sui)',18:'Corrupting (Gu)',19:'Nearing (Lin)',20:'Viewing (Guan)',
  21:'Gnawing Bite',22:'Adorning (Bi)',23:'Stripping (Bo)',24:'Returning (Fu)',
  25:'Without Embroiling',26:'Great Accumulating',27:'Swallowing (Yi)',28:'Great Exceeding',
  29:'Gorge (Kan)',30:'Radiance (Li)',31:'Conjoining (Xian)',32:'Persevering (Heng)',
  33:'Retiring (Dun)',34:'Great Invigorating',35:'Prospering (Jin)',36:'Brightness Hiding',
  37:'Dwelling People',38:'Polarising (Kui)',39:'Limping (Jian)',40:'Taking-Apart (Xie)',
  41:'Diminishing (Sun)',42:'Augmenting (Yi)',43:'Displacement (Guai)',44:'Coupling (Gou)',
  45:'Clustering (Cui)',46:'Ascending (Sheng)',47:'Confining (Kun)',48:'The Well (Jing)',
  49:'Skinning (Ge)',50:'The Vessel (Ding)',51:'Shake (Zhen)',52:'Bound (Gen)',
  53:'Infiltrating (Jian)',54:'Converting Maiden',55:'Abounding (Feng)',56:'Sojourning (Lu)',
  57:'Ground (Xun)',58:'Open (Dui)',59:'Dispersing (Huan)',60:'Articulating (Jie)',
  61:'Center Returning',62:'Small Exceeding',63:'Already Fording',64:'Not-Yet Fording'
};

var hexNum = KING_WEN[primary] || 0;
var resHexNum = changing.length > 0 ? (KING_WEN[resulting] || 0) : 0;

setGlobal('LD_ICHING_LINES', lines.join(','));
setGlobal('LD_ICHING_HEX_NUM', hexNum);
setGlobal('LD_ICHING_HEX_NAME', NAMES[hexNum] || 'Unknown');
setGlobal('LD_ICHING_CHANGING', changing.join(','));
setGlobal('LD_ICHING_RESULT_NUM', resHexNum);
setGlobal('LD_ICHING_RESULT_NAME', resHexNum ? (NAMES[resHexNum] || 'Unknown') : 'none');
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="15"/>
		</Action>

		<!-- A4. Write File: Save casting -->
		<Action sr="act3" ve="7">
			<code>410</code>
			<Str sr="arg0" ve="3">Documents/LifeData/spool/oracle/iching_%TIMES.csv</Str>
			<Str sr="arg1" ve="3">%TIMES,%TIME,%TIMEZONE,%LD_ICHING_METHOD,%LD_ICHING_HEX_NUM,%LD_ICHING_HEX_NAME,%LD_ICHING_LINES,%LD_ICHING_CHANGING,%LD_ICHING_RESULT_NUM,%LD_ICHING_RESULT_NAME</Str>
			<Int sr="arg2" val="0"/>
			<Int sr="arg3" val="1"/>
		</Action>

		<!-- A5. Flash: Primary hexagram -->
		<Action sr="act4" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Hexagram %LD_ICHING_HEX_NUM: %LD_ICHING_HEX_NAME</Str>
			<Int sr="arg1" val="1"/>
		</Action>

		<!-- A6. If: Has changing lines -->
		<Action sr="act5" ve="7">
			<code>37</code>
			<Str sr="arg0" ve="3">%LD_ICHING_CHANGING</Str>
			<Int sr="arg1" val="12"/>
			<Str sr="arg2" ve="3"></Str>
		</Action>

		<!-- A7. Flash: Changing lines result -->
		<Action sr="act6" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Moving lines: %LD_ICHING_CHANGING -> %LD_ICHING_RESULT_NUM: %LD_ICHING_RESULT_NAME</Str>
			<Int sr="arg1" val="1"/>
		</Action>

		<!-- A8. End If -->
		<Action sr="act7" ve="7">
			<code>38</code>
		</Action>
	</Task>
</TaskerData>
```

**CSV Format:** `epoch,time,timezone,method,hex_num,hex_name,lines,changing_lines,result_num,result_name`

---

## Task 351: RNG_Sample

**Module:** Oracle (XI)
**Purpose:** Hardware RNG sampling (100 bytes via SecureRandom). Silent background task.
**Duration:** <1 second
**Trigger:** Profile LD_RNG (every 30 minutes)

```xml
<TaskerData sr="" dession="all" tv="6.3.14">
	<Task sr="task351">
		<cdate>1711900000000</cdate>
		<edate>1711900000000</edate>
		<id>351</id>
		<nme>RNG_Sample</nme>
		<pri>100</pri>

		<!-- A1. JavaScriptlet: Generate 100 random bytes, compute mean and z-score -->
		<Action sr="act0" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var sr = new java.security.SecureRandom();
var bytes = java.lang.reflect.Array.newInstance(java.lang.Byte.TYPE, 100);
sr.nextBytes(bytes);

var values = [];
var sum = 0;
for (var i = 0; i &lt; 100; i++) {
  var v = bytes[i] &amp; 0xFF;
  values.push(v);
  sum += v;
}
var mean = sum / 100;
var z = (mean - 127.5) / 7.39;

setGlobal('LD_RNG_MEAN', mean.toFixed(2));
setGlobal('LD_RNG_Z', z.toFixed(4));
setGlobal('LD_RNG_RAW', values.join(','));
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="10"/>
		</Action>

		<!-- A2. Write File: Summary (mean + z-score) -->
		<Action sr="act1" ve="7">
			<code>410</code>
			<Str sr="arg0" ve="3">Documents/LifeData/spool/oracle/rng_%TIMES.csv</Str>
			<Str sr="arg1" ve="3">%TIMES,%TIME,%TIMEZONE,%LD_RNG_MEAN,%LD_RNG_Z</Str>
			<Int sr="arg2" val="0"/>
			<Int sr="arg3" val="1"/>
		</Action>

		<!-- A3. Write File: Raw 100-byte sequence (separate file) -->
		<Action sr="act2" ve="7">
			<code>410</code>
			<Str sr="arg0" ve="3">Documents/LifeData/spool/oracle/rng_raw_%TIMES.csv</Str>
			<Str sr="arg1" ve="3">%LD_RNG_RAW</Str>
			<Int sr="arg2" val="0"/>
			<Int sr="arg3" val="1"/>
		</Action>
	</Task>
</TaskerData>
```

**CSV Format (summary):** `epoch,time,timezone,mean,z_score`
**CSV Format (raw):** comma-separated 100 unsigned byte values (0-255)

---

## Task 352: IChing_Auto

**Module:** Oracle (XI)
**Purpose:** Automated daily I Ching casting (silent, observational, no question).
**Duration:** <1 second
**Trigger:** Profile LD_IChing_Daily (6:00 AM daily)

```xml
<TaskerData sr="" dession="all" tv="6.3.14">
	<Task sr="task352">
		<cdate>1711900000000</cdate>
		<edate>1711900000000</edate>
		<id>352</id>
		<nme>IChing_Auto</nme>
		<pri>100</pri>

		<!-- A1. JavaScriptlet: Coin-method casting (same algorithm as 350) -->
		<Action sr="act0" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var lines = [];
function coinLine() {
  var sum = 0;
  for (var c = 0; c &lt; 3; c++) {
    sum += Math.random() &lt; 0.5 ? 3 : 2;
  }
  return sum;
}
for (var i = 0; i &lt; 6; i++) { lines.push(coinLine()); }

var primary = 0;
var resulting = 0;
var changing = [];
for (var i = 5; i >= 0; i--) {
  var yang = (lines[i] === 7 || lines[i] === 9) ? 1 : 0;
  primary = (primary &lt;&lt; 1) | yang;
  var res_yang = yang;
  if (lines[i] === 6) { res_yang = 1; changing.push(i + 1); }
  if (lines[i] === 9) { res_yang = 0; changing.push(i + 1); }
  resulting = (resulting &lt;&lt; 1) | res_yang;
}

var KING_WEN = {
  0:2,1:23,2:8,3:20,4:16,5:35,6:45,7:12,
  8:15,9:52,10:39,11:53,12:62,13:56,14:31,15:33,
  16:7,17:4,18:29,19:59,20:40,21:64,22:47,23:6,
  24:46,25:18,26:48,27:57,28:32,29:50,30:28,31:44,
  32:24,33:27,34:3,35:42,36:51,37:21,38:17,39:25,
  40:36,41:22,42:63,43:37,44:55,45:30,46:49,47:13,
  48:19,49:41,50:60,51:61,52:54,53:38,54:58,55:10,
  56:11,57:26,58:5,59:9,60:34,61:14,62:43,63:1
};

var NAMES = {
  1:'Force (Qian)',2:'Field (Kun)',3:'Sprouting (Zhun)',4:'Enveloping (Meng)',
  5:'Attending (Xu)',6:'Conflict (Song)',7:'Leading (Shi)',8:'Grouping (Bi)',
  9:'Small Accumulating',10:'Treading (Lu)',11:'Pervading (Tai)',12:'Obstruction (Pi)',
  13:'Concording People',14:'Great Possessing',15:'Humbling (Qian)',16:'Providing-For (Yu)',
  17:'Following (Sui)',18:'Corrupting (Gu)',19:'Nearing (Lin)',20:'Viewing (Guan)',
  21:'Gnawing Bite',22:'Adorning (Bi)',23:'Stripping (Bo)',24:'Returning (Fu)',
  25:'Without Embroiling',26:'Great Accumulating',27:'Swallowing (Yi)',28:'Great Exceeding',
  29:'Gorge (Kan)',30:'Radiance (Li)',31:'Conjoining (Xian)',32:'Persevering (Heng)',
  33:'Retiring (Dun)',34:'Great Invigorating',35:'Prospering (Jin)',36:'Brightness Hiding',
  37:'Dwelling People',38:'Polarising (Kui)',39:'Limping (Jian)',40:'Taking-Apart (Xie)',
  41:'Diminishing (Sun)',42:'Augmenting (Yi)',43:'Displacement (Guai)',44:'Coupling (Gou)',
  45:'Clustering (Cui)',46:'Ascending (Sheng)',47:'Confining (Kun)',48:'The Well (Jing)',
  49:'Skinning (Ge)',50:'The Vessel (Ding)',51:'Shake (Zhen)',52:'Bound (Gen)',
  53:'Infiltrating (Jian)',54:'Converting Maiden',55:'Abounding (Feng)',56:'Sojourning (Lu)',
  57:'Ground (Xun)',58:'Open (Dui)',59:'Dispersing (Huan)',60:'Articulating (Jie)',
  61:'Center Returning',62:'Small Exceeding',63:'Already Fording',64:'Not-Yet Fording'
};

var hexNum = KING_WEN[primary] || 0;
var resHexNum = changing.length > 0 ? (KING_WEN[resulting] || 0) : 0;

setGlobal('LD_ICHING_AUTO_LINES', lines.join(','));
setGlobal('LD_ICHING_AUTO_HEX_NUM', hexNum);
setGlobal('LD_ICHING_AUTO_HEX_NAME', NAMES[hexNum] || 'Unknown');
setGlobal('LD_ICHING_AUTO_CHANGING', changing.join(','));
setGlobal('LD_ICHING_AUTO_RESULT_NUM', resHexNum);
setGlobal('LD_ICHING_AUTO_RESULT_NAME', resHexNum ? (NAMES[resHexNum] || 'Unknown') : 'none');
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="15"/>
		</Action>

		<!-- A2. Write File: Save auto-casting -->
		<Action sr="act1" ve="7">
			<code>410</code>
			<Str sr="arg0" ve="3">Documents/LifeData/spool/oracle/iching_auto_%TIMES.csv</Str>
			<Str sr="arg1" ve="3">%TIMES,%TIME,%TIMEZONE,coin_auto,%LD_ICHING_AUTO_HEX_NUM,%LD_ICHING_AUTO_HEX_NAME,%LD_ICHING_AUTO_LINES,%LD_ICHING_AUTO_CHANGING,%LD_ICHING_AUTO_RESULT_NUM,%LD_ICHING_AUTO_RESULT_NAME</Str>
			<Int sr="arg2" val="0"/>
			<Int sr="arg3" val="1"/>
		</Action>
	</Task>
</TaskerData>
```

**CSV Format:** Same as Task 350 but method is always `coin_auto`. No flash (silent).

---

## Task 360: Log_Unlock_Latency

**Module:** Behavior (OMICRON)
**Purpose:** Measures time from screen unlock to first app interaction. Passive.
**Duration:** Automatic (event-driven)
**Trigger:** Profile LD_UnlockLatency (Display Unlocked event)

```xml
<TaskerData sr="" dession="all" tv="6.3.14">
	<Task sr="task360">
		<cdate>1711900000000</cdate>
		<edate>1711900000000</edate>
		<id>360</id>
		<nme>Log_Unlock_Latency</nme>
		<pri>100</pri>

		<!-- A1. Variable Set: %LD_UNLOCK_START = %TIMEMS -->
		<Action sr="act0" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_UNLOCK_START</Str>
			<Str sr="arg1" ve="3">%TIMEMS</Str>
			<Int sr="arg2" val="0"/>
		</Action>

		<!-- A2. Wait: Up to 30 seconds for app change -->
		<Action sr="act1" ve="7">
			<code>30</code>
			<Int sr="arg0" val="0"/>
			<Int sr="arg1" val="0"/>
			<Int sr="arg2" val="30"/>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A3. Variable Set: %LD_UNLOCK_APP = %WIN (current foreground app) -->
		<Action sr="act2" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_UNLOCK_APP</Str>
			<Str sr="arg1" ve="3">%WIN</Str>
			<Int sr="arg2" val="0"/>
		</Action>

		<!-- A4. Variable Set: Compute latency (math) -->
		<Action sr="act3" ve="7">
			<code>547</code>
			<Str sr="arg0" ve="3">%LD_UNLOCK_LATENCY</Str>
			<Str sr="arg1" ve="3">%TIMEMS - %LD_UNLOCK_START</Str>
			<Int sr="arg2" val="1"/>
		</Action>

		<!-- A5. If: Latency > 30000 (timeout) -> Stop -->
		<Action sr="act4" ve="7">
			<code>37</code>
			<Str sr="arg0" ve="3">%LD_UNLOCK_LATENCY</Str>
			<Int sr="arg1" val="3"/>
			<Str sr="arg2" ve="3">30000</Str>
		</Action>
		<Action sr="act5" ve="7">
			<code>137</code>
		</Action>
		<Action sr="act6" ve="7">
			<code>38</code>
		</Action>

		<!-- A6. If: Latency < 200 (too fast, false trigger) -> Stop -->
		<Action sr="act7" ve="7">
			<code>37</code>
			<Str sr="arg0" ve="3">%LD_UNLOCK_LATENCY</Str>
			<Int sr="arg1" val="7"/>
			<Str sr="arg2" ve="3">200</Str>
		</Action>
		<Action sr="act8" ve="7">
			<code>137</code>
		</Action>
		<Action sr="act9" ve="7">
			<code>38</code>
		</Action>

		<!-- A7. Write File: Save unlock latency -->
		<Action sr="act10" ve="7">
			<code>410</code>
			<Str sr="arg0" ve="3">Documents/LifeData/spool/behavior/unlock_%TIMES.csv</Str>
			<Str sr="arg1" ve="3">%TIMES,%TIME,%TIMEZONE,%LD_UNLOCK_LATENCY,%LD_UNLOCK_APP</Str>
			<Int sr="arg2" val="0"/>
			<Int sr="arg3" val="1"/>
		</Action>
	</Task>
</TaskerData>
```

**CSV Format:** `epoch,time,timezone,latency_ms,first_app`

**Note:** The Wait action (A2) is a simplified approach. Ideally, use a "Wait Until" condition on `%WIN` changing, or trigger via a secondary profile on App Changed that sets a variable. See the Written List for the refined two-profile approach if simple Wait proves unreliable.

---

## Task 370: Log_Steps_Hourly

**Module:** Behavior (OMICRON)
**Purpose:** Logs hourly step count delta from Android step counter sensor.
**Duration:** <2 seconds
**Trigger:** Profile LD_Steps (every 1 hour)

```xml
<TaskerData sr="" dession="all" tv="6.3.14">
	<Task sr="task370">
		<cdate>1711900000000</cdate>
		<edate>1711900000000</edate>
		<id>370</id>
		<nme>Log_Steps_Hourly</nme>
		<pri>100</pri>

		<!-- A1. JavaScriptlet: Read step counter via Android sensor API -->
		<Action sr="act0" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var sm = context.getSystemService(context.SENSOR_SERVICE);
var sc = sm.getDefaultSensor(19);
if (sc === null) {
  setGlobal('LD_STEPS_AVAILABLE', '0');
} else {
  var listener = new android.hardware.SensorEventListener({
    onSensorChanged: function(event) {
      setGlobal('LD_STEP_COUNTER', Math.floor(event.values[0]));
      setGlobal('LD_STEPS_AVAILABLE', '1');
      sm.unregisterListener(this);
    },
    onAccuracyChanged: function(sensor, accuracy) {}
  });
  sm.registerListener(listener, sc,
    android.hardware.SensorManager.SENSOR_DELAY_NORMAL);
}
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="10"/>
		</Action>

		<!-- A2. Wait: 1 second for sensor callback -->
		<Action sr="act1" ve="7">
			<code>30</code>
			<Int sr="arg0" val="0"/>
			<Int sr="arg1" val="0"/>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A3. If: Sensor unavailable -> Stop -->
		<Action sr="act2" ve="7">
			<code>37</code>
			<Str sr="arg0" ve="3">%LD_STEPS_AVAILABLE</Str>
			<Int sr="arg1" val="0"/>
			<Str sr="arg2" ve="3">0</Str>
		</Action>
		<Action sr="act3" ve="7">
			<code>137</code>
		</Action>
		<Action sr="act4" ve="7">
			<code>38</code>
		</Action>

		<!-- A4. JavaScriptlet: Compute hourly delta -->
		<Action sr="act5" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var counter = parseInt(global('LD_STEP_COUNTER'));
var prev = global('LD_PREV_STEP_COUNT');
var hourly = 0;

if (prev &amp;&amp; prev !== '%LD_PREV_STEP_COUNT') {
  prev = parseInt(prev);
  hourly = counter - prev;
  if (hourly &lt; 0) {
    hourly = counter;
  }
} else {
  hourly = 0;
}

setGlobal('LD_HOURLY_STEPS', hourly);
setGlobal('LD_PREV_STEP_COUNT', counter);
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="5"/>
		</Action>

		<!-- A5. Write File: Save hourly steps -->
		<Action sr="act6" ve="7">
			<code>410</code>
			<Str sr="arg0" ve="3">Documents/LifeData/spool/behavior/steps_%TIMES.csv</Str>
			<Str sr="arg1" ve="3">%TIMES,%TIME,%TIMEZONE,%LD_HOURLY_STEPS,%LD_STEP_COUNTER</Str>
			<Int sr="arg2" val="0"/>
			<Int sr="arg3" val="1"/>
		</Action>
	</Task>
</TaskerData>
```

**CSV Format:** `epoch,time,timezone,hourly_steps,total_step_counter`

---

## Task 380: Dream_Quick_Log

**Module:** Behavior (OMICRON)
**Purpose:** Structured dream capture (vividness, tone, keywords, auto-detected themes).
**Duration:** ~30 seconds
**Trigger:** Widget / alarm dismissal chain

```xml
<TaskerData sr="" dession="all" tv="6.3.14">
	<Task sr="task380">
		<cdate>1711900000000</cdate>
		<edate>1711900000000</edate>
		<id>380</id>
		<nme>Dream_Quick_Log</nme>
		<pri>100</pri>

		<!-- A1. Variable Query: Vividness (1-10) -->
		<Action sr="act0" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_DREAM_VIVID</Str>
			<Str sr="arg1" ve="3">Dream Vividness (1-10)
1 = barely remember, 10 = cinematic</Str>
			<Str sr="arg2" ve="3">5</Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A2. Variable Query: Emotional tone -->
		<Action sr="act1" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_DREAM_TONE</Str>
			<Str sr="arg1" ve="3">Emotional Tone
(Positive/Negative/Neutral/Mixed/Terrifying/Euphoric/Surreal/Mundane)</Str>
			<Str sr="arg2" ve="3">Neutral</Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A3. Variable Query: Keywords -->
		<Action sr="act2" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_DREAM_KEYWORDS</Str>
			<Str sr="arg1" ve="3">Key images/events (comma-separated)
e.g. flying, ocean, old house, chased</Str>
			<Str sr="arg2" ve="3"></Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A4. JavaScriptlet: Auto-detect themes from keywords -->
		<Action sr="act3" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var kw = global('LD_DREAM_KEYWORDS').toLowerCase();
var themes = [];
var themeMap = {
  'chase': ['chase','chasing','running from','pursued','escape','fled'],
  'falling': ['falling','fell','dropped','cliff','plummet'],
  'flying': ['flying','float','soaring','levitat','wings'],
  'water': ['ocean','river','lake','swim','drown','flood','rain','beach','sea'],
  'death': ['death','dying','dead','funeral','killed','murder'],
  'teeth': ['teeth','tooth'],
  'school': ['school','class','exam','test','teacher','homework','university'],
  'work': ['work','boss','coworker','meeting','office','butcher','meat'],
  'animal': ['dog','cat','snake','bird','bear','wolf','spider','deer','fish','horse'],
  'vehicle': ['car','driving','bus','train','airplane','crash','bike'],
  'house': ['house','room','door','window','basement','attic','hallway'],
  'lost': ['lost','searching','cant find','looking for','maze','wander'],
  'lucid': ['realized','knew i was dreaming','lucid','controlled','aware'],
  'social': ['friend','family','party','crowd','stranger','talking','argue'],
  'nature': ['forest','mountain','sky','stars','moon','sun','garden','tree']
};
for (var theme in themeMap) {
  for (var i = 0; i &lt; themeMap[theme].length; i++) {
    if (kw.indexOf(themeMap[theme][i]) >= 0) {
      themes.push(theme);
      break;
    }
  }
}
setGlobal('LD_DREAM_THEMES', themes.join(',') || 'unclassified');
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="10"/>
		</Action>

		<!-- A5. Write File: Save dream log -->
		<Action sr="act4" ve="7">
			<code>410</code>
			<Str sr="arg0" ve="3">Documents/LifeData/spool/behavior/dream_%TIMES.csv</Str>
			<Str sr="arg1" ve="3">%TIMES,%TIME,%TIMEZONE,%LD_DREAM_VIVID,%LD_DREAM_TONE,%LD_DREAM_KEYWORDS,%LD_DREAM_THEMES</Str>
			<Int sr="arg2" val="0"/>
			<Int sr="arg3" val="1"/>
		</Action>

		<!-- A6. Flash: Confirmation -->
		<Action sr="act5" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Dream logged: %LD_DREAM_THEMES (vividness: %LD_DREAM_VIVID)</Str>
			<Int sr="arg1" val="1"/>
		</Action>
	</Task>
</TaskerData>
```

**CSV Format:** `epoch,time,timezone,vividness,emotional_tone,keywords,themes`

---

## Task 381: Dream_Structured_Recall

**Module:** Behavior (OMICRON)
**Purpose:** Extended structured dream capture for notable dreams.
**Duration:** ~60-120 seconds
**Trigger:** Widget / manual (optionally chained after Task 380 on high-vividness dreams)

```xml
<TaskerData sr="" dession="all" tv="6.3.14">
	<Task sr="task381">
		<cdate>1711900000000</cdate>
		<edate>1711900000000</edate>
		<id>381</id>
		<nme>Dream_Structured_Recall</nme>
		<pri>100</pri>

		<!-- A1. Variable Query: Settings -->
		<Action sr="act0" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_DREAM_SETTING</Str>
			<Str sr="arg1" ve="3">Setting(s):
e.g. childhood home, underwater city</Str>
			<Str sr="arg2" ve="3"></Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A2. Variable Query: Characters -->
		<Action sr="act1" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_DREAM_CHARS</Str>
			<Str sr="arg1" ve="3">Characters:
e.g. mom, unknown old man, coworker</Str>
			<Str sr="arg2" ve="3"></Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A3. Variable Query: Actions/events -->
		<Action sr="act2" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_DREAM_ACTIONS</Str>
			<Str sr="arg1" ve="3">Key actions/events:
e.g. searching for something, discovered hidden room</Str>
			<Str sr="arg2" ve="3"></Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A4. Variable Query: Strongest emotion -->
		<Action sr="act3" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_DREAM_EMOTION</Str>
			<Str sr="arg1" ve="3">Strongest emotion during dream:</Str>
			<Str sr="arg2" ve="3"></Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A5. Variable Query: Connection to waking life -->
		<Action sr="act4" ve="7">
			<code>545</code>
			<Str sr="arg0" ve="3">%LD_DREAM_CONNECTION</Str>
			<Str sr="arg1" ve="3">Any connection to waking life? (optional)</Str>
			<Str sr="arg2" ve="3">none</Str>
			<Int sr="arg3" val="0"/>
		</Action>

		<!-- A6. Write File: Save structured dream recall -->
		<Action sr="act5" ve="7">
			<code>410</code>
			<Str sr="arg0" ve="3">Documents/LifeData/spool/behavior/dream_detail_%TIMES.csv</Str>
			<Str sr="arg1" ve="3">%TIMES,%TIME,%TIMEZONE,%LD_DREAM_SETTING,%LD_DREAM_CHARS,%LD_DREAM_ACTIONS,%LD_DREAM_EMOTION,%LD_DREAM_CONNECTION</Str>
			<Int sr="arg2" val="0"/>
			<Int sr="arg3" val="1"/>
		</Action>

		<!-- A7. Flash: Confirmation -->
		<Action sr="act6" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Detailed dream recorded</Str>
			<Int sr="arg1" val="0"/>
		</Action>
	</Task>
</TaskerData>
```

**CSV Format:** `epoch,time,timezone,settings,characters,actions,emotion,connection`

---

## Profiles

Profiles must be created manually in the Tasker UI. Below are the specifications for each.

### Profile: LD_UnlockLatency

| Field | Value |
|-------|-------|
| **Name** | LD_UnlockLatency |
| **Type** | Event |
| **Event** | Display > Display Unlocked |
| **Task** | Log_Unlock_Latency (360) |

**Setup:** Tasker > Profiles tab > **+** > Event > Display > Display Unlocked > Back > Select task "Log_Unlock_Latency"

### Profile: LD_Steps

| Field | Value |
|-------|-------|
| **Name** | LD_Steps |
| **Type** | Time |
| **From** | 00:00 |
| **To** | 23:59 |
| **Repeat** | Every 1 hour |
| **Task** | Log_Steps_Hourly (370) |

**Setup:** Tasker > Profiles tab > **+** > Time > Set From: 00:00, To: 23:59, check "Repeat" and set interval to 1 hour > Back > Select task "Log_Steps_Hourly"

### Profile: LD_RNG

| Field | Value |
|-------|-------|
| **Name** | LD_RNG |
| **Type** | Time |
| **From** | 00:00 |
| **To** | 23:59 |
| **Repeat** | Every 30 minutes |
| **Task** | RNG_Sample (351) |

**Setup:** Tasker > Profiles tab > **+** > Time > Set From: 00:00, To: 23:59, check "Repeat" and set interval to 30 minutes > Back > Select task "RNG_Sample"

### Profile: LD_IChing_Daily

| Field | Value |
|-------|-------|
| **Name** | LD_IChing_Daily |
| **Type** | Time |
| **From** | 06:00 |
| **To** | 06:05 |
| **Repeat** | Off |
| **Task** | IChing_Auto (352) |

**Setup:** Tasker > Profiles tab > **+** > Time > Set From: 06:00, To: 06:05 > Back > Select task "IChing_Auto"

### Profile: LD_DreamPrompt (Optional)

| Field | Value |
|-------|-------|
| **Name** | LD_DreamPrompt |
| **Type** | Event |
| **Event** | Alarm > Alarm Done (or Alarm Dismissed) |
| **Task** | Dream_Quick_Log (380) |

**Setup:** Tasker > Profiles tab > **+** > Event > Alarm > Alarm Done > Back > Select task "Dream_Quick_Log"

**Note:** This auto-triggers dream logging after alarm dismissal. Disable this profile if you don't want the prompt every morning.

---

## Widget Setup

For manually-triggered tasks, create home screen widgets:

| Task | Widget Label | Suggested Icon |
|------|-------------|----------------|
| Digit_Span (310) | Digit Span | Brain icon |
| Typing_Speed_Test (330) | Type Test | Keyboard icon |
| Cognitive_Battery (340) | Cog Battery | Lightning bolt |
| IChing_Cast (350) | I Ching | Trigram symbol |
| Dream_Quick_Log (380) | Dream Log | Moon icon |
| Dream_Structured_Recall (381) | Dream Detail | Notebook icon |

**To create:** Long-press home screen > Widgets > Tasker > Task Shortcut > Select task > Choose icon

---

## Spool Directory Setup

Before first use, create the spool directories on your phone:

```
Documents/LifeData/spool/cognition/
Documents/LifeData/spool/behavior/
Documents/LifeData/spool/oracle/
```

Tasker's Write File action will create files but NOT directories. Create these manually via a file manager or run this one-time Tasker task:

```xml
<TaskerData sr="" dession="all" tv="6.3.14">
	<Task sr="taskSetup">
		<cdate>1711900000000</cdate>
		<edate>1711900000000</edate>
		<id>999</id>
		<nme>LD_Create_Spool_Dirs</nme>
		<pri>100</pri>

		<Action sr="act0" ve="7">
			<code>129</code>
			<Str sr="arg0" ve="3">
var dirs = [
  'Documents/LifeData/spool/cognition',
  'Documents/LifeData/spool/behavior',
  'Documents/LifeData/spool/oracle'
];
for (var i = 0; i &lt; dirs.length; i++) {
  var f = new java.io.File(
    android.os.Environment.getExternalStorageDirectory(), dirs[i]);
  f.mkdirs();
}
setGlobal('LD_SPOOL_SETUP', 'done');
			</Str>
			<Str sr="arg1" ve="3"></Str>
			<Int sr="arg2" val="1"/>
			<Int sr="arg3" val="10"/>
		</Action>

		<Action sr="act1" ve="7">
			<code>548</code>
			<Str sr="arg0" ve="3">Spool directories created: %LD_SPOOL_SETUP</Str>
			<Int sr="arg1" val="1"/>
		</Action>
	</Task>
</TaskerData>
```

Run this task once before deploying any other tasks.
