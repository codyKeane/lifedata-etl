# Tasker Manual Task Creation Guide — LifeData V4

> **These tasks require custom Tasker Scenes** (visual UI elements with tap detection)
> and cannot be fully expressed as importable XML. Follow the step-by-step instructions
> below to create each task and its associated Scene in the Tasker UI.
>
> **Prerequisites:**
> - Tasker 6.x installed with JavaScript engine enabled
> - Spool directories created (see `TASKER_XML_LIST.md` > Spool Directory Setup)
> - All XML-based tasks from `TASKER_XML_LIST.md` imported first (Task 340 depends on these)

---

## Table of Contents

1. [Task 300: Simple_RT (Reaction Time)](#task-300-simple_rt)
2. [Task 301: Choice_RT (Discrimination Reaction Time)](#task-301-choice_rt)
3. [Task 302: Go_NoGo (Inhibitory Control)](#task-302-go_nogo)
4. [Task 320: Time_Production (Time Perception)](#task-320-time_production)
5. [Task 321: Time_Estimation (Reverse Time Probe)](#task-321-time_estimation)
6. [Scene Creation Reference](#scene-creation-reference)

---

## Task 300: Simple_RT

**Module:** Cognition (NU)
**Purpose:** Measures simple reaction time across 3 trials with randomized foreperiods. The most reliable single cognitive probe in the system.
**Duration:** ~10-15 seconds
**Trigger:** Widget (recommended: chain after Morning_Checkin, before bed, 2x during day)
**Scene Required:** `FullscreenColor`

### Step 1: Create Scene "FullscreenColor"

1. Open Tasker > **Scenes** tab
2. Tap **+** to create a new scene
3. Name it `FullscreenColor`
4. Set scene properties:
   - **Geometry:** Full screen (Width: 100%, Height: 100%)
   - **Background Color:** Will be set dynamically (default: black)
5. Add one element:
   - **Element type:** Rectangle
   - **Name:** `bg_rect`
   - **Position:** X=0, Y=0
   - **Size:** Width=100%, Height=100%
   - **Background Color:** `%LD_RT_COLOR` (use variable)
6. On the **Tap** tab of `bg_rect`:
   - Add action: **Variable Set** > `%LD_RT_END` to `%TIMEMS`
   - Add action: **Scene Destroy** > `FullscreenColor`

### Step 2: Create Task "Simple_RT"

Create a new task named `Simple_RT` with these actions in order:

**Action 1: Variable Set**
- Name: `%LD_RT_TRIAL`
- To: `0`

**Action 2: Variable Set**
- Name: `%LD_RT_RESULTS`
- To: (empty string)

**--- LOOP START (label: "LOOP") ---**

**Action 3: Variable Set** (Do Maths: ON)
- Name: `%LD_RT_TRIAL`
- To: `%LD_RT_TRIAL + 1`

**Action 4: Flash**
- Text: `Trial %LD_RT_TRIAL - Wait...`
- Duration: Short

**Action 5: JavaScriptlet**
```javascript
var wait = Math.floor(Math.random() * 2501) + 1500;
setGlobal('LD_RT_WAIT', wait);
var colors = ['red', 'green', 'blue', 'yellow'];
var color = colors[Math.floor(Math.random() * colors.length)];
setGlobal('LD_RT_COLOR', color);
```

**Action 6: Wait**
- Milliseconds: `%LD_RT_WAIT`

**Action 7: Variable Set**
- Name: `%LD_RT_START`
- To: `%TIMEMS`

**Action 8: Scene Show**
- Name: `FullscreenColor`
- Display As: Overlay, Blocking
- (The scene displays a fullscreen color; tapping sets %LD_RT_END and destroys the scene)

**Action 9: Variable Set** (Do Maths: ON)
- Name: `%LD_RT_MS`
- To: `%LD_RT_END - %LD_RT_START`

**Action 10: If** `%LD_RT_MS < 100`
- **Action 11: Flash** - Text: `Too fast - anticipatory. Retrying.`
- **Action 12: Goto** - Type: Action Label, Label: `LOOP`
- **End If**

**Action 13: If** `%LD_RT_MS > 2000`
- **Action 14: Flash** - Text: `Too slow - distracted. Retrying.`
- **Action 15: Goto** - Type: Action Label, Label: `LOOP`
- **End If**

**Action 16: Variable Set** (Append: ON)
- Name: `%LD_RT_RESULTS`
- To: `|%LD_RT_COLOR:%LD_RT_MS:%LD_RT_WAIT`

**Action 17: If** `%LD_RT_TRIAL < 3`
- **Action 18: Goto** - Type: Action Label, Label: `LOOP`
- **End If**

**--- LOOP END ---**

**Action 19: Write File**
- File: `Documents/LifeData/spool/cognition/simple_rt_%TIMES.csv`
- Text: `%TIMES,%TIME,%TIMEZONE,%LD_RT_RESULTS`
- Append: OFF

**Action 20: JavaScriptlet**
```javascript
var parts = global('LD_RT_RESULTS').split('|').filter(Boolean);
var times = parts.map(function(p) { return parseInt(p.split(':')[1]); });
times.sort(function(a,b) { return a - b; });
var median = times[Math.floor(times.length / 2)];
setGlobal('LD_RT_MEDIAN', median);
```

**Action 21: Flash**
- Text: `RT: %LD_RT_MEDIAN ms (median of 3)`
- Duration: Long

### Step 3: Create Widget

- Long-press home screen > Widgets > Tasker > Task Shortcut
- Select `Simple_RT`
- Icon: Lightning bolt

**CSV Format:** `epoch,time,timezone,trial_data`
Where `trial_data` = pipe-delimited `color:rt_ms:wait_ms` triplets.

---

## Task 301: Choice_RT

**Module:** Cognition (NU)
**Purpose:** Measures discrimination reaction time (left vs. right choice). Isolates cognitive processing time beyond simple motor response.
**Duration:** ~30 seconds (5 trials)
**Trigger:** Widget / manual
**Scene Required:** `ChoiceRT`

### Step 1: Create Scene "ChoiceRT"

1. Open Tasker > **Scenes** tab
2. Tap **+** > Name: `ChoiceRT`
3. Set scene properties:
   - **Geometry:** Full screen (Width: 100%, Height: 100%)
   - **Background Color:** Dark gray (#333333)
4. Add three elements:

   **Element A: Text "arrow_display"**
   - Position: Centered horizontally, top 30% of screen
   - Text Size: 72sp
   - Text: `%LD_CRT_ARROW` (will be set to left or right arrow unicode)
   - Text Color: White

   **Element B: Button "btn_left"**
   - Position: Left half of screen, bottom 50%
   - Size: 50% width, 40% height
   - Text: `LEFT`
   - Text Size: 36sp
   - Background Color: #2196F3 (blue)
   - **Tap action:**
     1. Variable Set: `%LD_CRT_RESPONSE` to `left`
     2. Variable Set: `%LD_CRT_END` to `%TIMEMS`
     3. Scene Destroy: `ChoiceRT`

   **Element C: Button "btn_right"**
   - Position: Right half of screen, bottom 50%
   - Size: 50% width, 40% height
   - Text: `RIGHT`
   - Text Size: 36sp
   - Background Color: #4CAF50 (green)
   - **Tap action:**
     1. Variable Set: `%LD_CRT_RESPONSE` to `right`
     2. Variable Set: `%LD_CRT_END` to `%TIMEMS`
     3. Scene Destroy: `ChoiceRT`

### Step 2: Create Task "Choice_RT"

**Action 1: Variable Set**
- Name: `%LD_CRT_TRIAL` | To: `0`

**Action 2: Variable Set**
- Name: `%LD_CRT_RESULTS` | To: (empty)

**--- LOOP START (label: "LOOP") ---**

**Action 3: Variable Set** (Do Maths: ON)
- Name: `%LD_CRT_TRIAL` | To: `%LD_CRT_TRIAL + 1`

**Action 4: JavaScriptlet**
```javascript
var target = Math.random() < 0.5 ? 'left' : 'right';
setGlobal('LD_CRT_TARGET', target);
// Unicode arrows: left = U+2190, right = U+2192
setGlobal('LD_CRT_ARROW', target === 'left' ? '\u2190' : '\u2192');
var wait = Math.floor(Math.random() * 2001) + 1500;
setGlobal('LD_CRT_WAIT', wait);
```

**Action 5: Wait**
- Milliseconds: `%LD_CRT_WAIT`

**Action 6: Variable Set**
- Name: `%LD_CRT_START` | To: `%TIMEMS`

**Action 7: Scene Show**
- Name: `ChoiceRT`
- Display As: Overlay, Blocking

**Action 8: Variable Set** (Do Maths: ON)
- Name: `%LD_CRT_MS` | To: `%LD_CRT_END - %LD_CRT_START`

**Action 9: JavaScriptlet**
```javascript
var correct = (global('LD_CRT_RESPONSE') === global('LD_CRT_TARGET')) ? 1 : 0;
setGlobal('LD_CRT_CORRECT', correct);
var results = global('LD_CRT_RESULTS');
var target = global('LD_CRT_TARGET');
var response = global('LD_CRT_RESPONSE');
var ms = global('LD_CRT_MS');
results = results + (results ? '|' : '') + target + ':' + response + ':' + ms + ':' + correct;
setGlobal('LD_CRT_RESULTS', results);
```

**Action 10: If** `%LD_CRT_TRIAL < 5`
- **Action 11: Goto** - Label: `LOOP`
- **End If**

**--- LOOP END ---**

**Action 12: Write File**
- File: `Documents/LifeData/spool/cognition/choice_rt_%TIMES.csv`
- Text: `%TIMES,%TIME,%TIMEZONE,choice,%LD_CRT_RESULTS`
- Append: OFF

**Action 13: Flash**
- Text: `Choice RT complete`
- Duration: Long

**CSV Format:** `epoch,time,timezone,choice,trial_data`
Where `trial_data` = pipe-delimited `target:response:rt_ms:correct` tuples.

---

## Task 302: Go_NoGo

**Module:** Cognition (NU)
**Purpose:** Measures inhibitory control. 70% "go" (green, tap) / 30% "nogo" (red, don't tap). Commission errors (tapping red) are the primary impulsivity/fatigue signal.
**Duration:** ~60 seconds (10 trials)
**Trigger:** Widget / manual
**Scene Required:** `GoNoGoScene`

### Step 1: Create Scene "GoNoGoScene"

1. Open Tasker > **Scenes** tab
2. Tap **+** > Name: `GoNoGoScene`
3. Set scene properties:
   - **Geometry:** Full screen
   - **Background Color:** Black (#000000)
4. Add one element:

   **Element: Oval "stimulus_circle"**
   - Position: Centered
   - Size: 200dp x 200dp (large, easy to tap)
   - Fill Color: Will be set dynamically (green for go, red for nogo)
   - **Tap action:**
     1. Variable Set: `%LD_GNG_RESPONDED` to `1`
     2. Variable Set: `%LD_GNG_END` to `%TIMEMS`
     3. Scene Destroy: `GoNoGoScene`

### Step 2: Create Task "Go_NoGo"

**Action 1: Variable Set**
- Name: `%LD_GNG_TRIAL` | To: `0`

**Action 2: Variable Set**
- Name: `%LD_GNG_RESULTS` | To: (empty)

**--- LOOP START (label: "LOOP") ---**

**Action 3: Variable Set** (Do Maths: ON)
- Name: `%LD_GNG_TRIAL` | To: `%LD_GNG_TRIAL + 1`

**Action 4: JavaScriptlet**
```javascript
// 70% go, 30% nogo
var type = Math.random() < 0.7 ? 'go' : 'nogo';
setGlobal('LD_GNG_TYPE', type);
var wait = Math.floor(Math.random() * 1501) + 1000;
setGlobal('LD_GNG_WAIT', wait);
```

**Action 5: Wait**
- Milliseconds: `%LD_GNG_WAIT`

**Action 6: Variable Set**
- Name: `%LD_GNG_RESPONDED` | To: `0`

**Action 7: Variable Set**
- Name: `%LD_GNG_START` | To: `%TIMEMS`

**Action 8: JavaScriptlet** (Set scene circle color based on trial type)
```javascript
var type = global('LD_GNG_TYPE');
// For the scene, we need to set the circle color before showing
// Green (#4CAF50) for go, Red (#F44336) for nogo
setGlobal('LD_GNG_CIRCLE_COLOR', type === 'go' ? '#4CAF50' : '#F44336');
```

**Action 9: Scene Show**
- Name: `GoNoGoScene`
- Display As: Overlay, Blocking

> **Important:** Before showing the scene, you need to update the circle color.
> In the Scene Editor, set `stimulus_circle` Fill Color to `%LD_GNG_CIRCLE_COLOR`.
> Alternatively, use Element Set Colour action before Scene Show.

**Action 10: Wait**
- Seconds: 1
- Milliseconds: 500
- (1.5 second response window)

**Action 11: Scene Destroy** (if still showing — response timeout)
- Name: `GoNoGoScene`

**Action 12: JavaScriptlet** (Score the trial)
```javascript
var type = global('LD_GNG_TYPE');
var responded = global('LD_GNG_RESPONDED') === '1';
var start = parseInt(global('LD_GNG_START'));
var end = parseInt(global('LD_GNG_END') || '0');
var rt = responded ? (end - start) : -1;
var correct;

if (type === 'go') {
  correct = responded ? 1 : 0;  // Miss if no response
} else {
  correct = responded ? 0 : 1;  // Commission error if responded to nogo
}

var results = global('LD_GNG_RESULTS');
results = results + (results ? '|' : '') + type + ':' + rt + ':' + correct;
setGlobal('LD_GNG_RESULTS', results);
```

**Action 13: If** `%LD_GNG_TRIAL < 10`
- **Action 14: Goto** - Label: `LOOP`
- **End If**

**--- LOOP END ---**

**Action 15: JavaScriptlet** (Compute summary statistics)
```javascript
var parts = global('LD_GNG_RESULTS').split('|').filter(Boolean);
var goRTs = [];
var commissionErrors = 0;
var totalNogo = 0;

parts.forEach(function(p) {
  var fields = p.split(':');
  var type = fields[0], rt = parseInt(fields[1]), correct = parseInt(fields[2]);
  if (type === 'go' && rt > 0 && correct === 1) goRTs.push(rt);
  if (type === 'nogo') {
    totalNogo++;
    if (correct === 0) commissionErrors++;
  }
});

var meanGoRT = goRTs.length > 0 ?
  Math.round(goRTs.reduce(function(a,b){return a+b;}, 0) / goRTs.length) : 0;
var errorRate = totalNogo > 0 ? Math.round((commissionErrors / totalNogo) * 100) : 0;

setGlobal('LD_GNG_MEAN_RT', meanGoRT);
setGlobal('LD_GNG_ERROR_RATE', errorRate);
```

**Action 16: Write File**
- File: `Documents/LifeData/spool/cognition/gonogo_%TIMES.csv`
- Text: `%TIMES,%TIME,%TIMEZONE,gonogo,%LD_GNG_RESULTS`
- Append: OFF

**Action 17: Flash**
- Text: `Go/NoGo: %LD_GNG_ERROR_RATE% errors, %LD_GNG_MEAN_RT ms avg`
- Duration: Long

**CSV Format:** `epoch,time,timezone,gonogo,trial_data`
Where `trial_data` = pipe-delimited `type:rt_ms:correct` tuples. (`rt=-1` means no response.)

---

## Task 320: Time_Production

**Module:** Cognition (NU)
**Purpose:** "Press when you think N seconds have elapsed." Measures internal clock speed and autonomic state.
**Duration:** ~15-35 seconds (depending on target interval)
**Trigger:** Widget / manual
**Scene Required:** `TimerScene`

### Step 1: Create Scene "TimerScene"

1. Open Tasker > **Scenes** tab
2. Tap **+** > Name: `TimerScene`
3. Set scene properties:
   - **Geometry:** Full screen
   - **Background Color:** Dark gray (#222222)
4. Add two elements:

   **Element A: Text "instruction_text"**
   - Position: Centered, top 20%
   - Text: `Tap to START`
   - Text Size: 28sp
   - Text Color: White
   - Visibility: Visible

   **Element B: Rectangle "tap_zone"**
   - Position: Full screen (X=0, Y=0, 100% x 100%)
   - Fill Color: Transparent
   - **Tap action:**
     1. If `%LD_TP_PHASE` equals `start`:
        - Variable Set: `%LD_TP_START` to `%TIMEMS`
        - Variable Set: `%LD_TP_PHASE` to `running`
        - Element Text: `instruction_text` > (empty, or set to minimal dot)
        - (All UI disappears during production interval)
     2. Else If `%LD_TP_PHASE` equals `running`:
        - Variable Set: `%LD_TP_END` to `%TIMEMS`
        - Scene Destroy: `TimerScene`

> **Implementation Note:** The two-phase tap handling is complex in a single scene element.
> **Alternative approach:** Use two scenes — `TimerStart` (tap to start) and `TimerRunning`
> (blank screen, tap to stop). Or use a single scene with a JavaScriptlet in the tap handler
> that checks the phase variable.

### Step 2: Create Task "Time_Production"

**Action 1: JavaScriptlet** (Select random target interval)
```javascript
var targets = [5, 10, 15, 30];
var target = targets[Math.floor(Math.random() * targets.length)];
setGlobal('LD_TP_TARGET', target);
```

**Action 2: Flash**
- Text: `Produce %LD_TP_TARGET seconds. Tap to start, then tap when you think the time is up.`
- Duration: Long

**Action 3: Wait**
- Seconds: 2 (let them read the instruction)

**Action 4: Variable Set**
- Name: `%LD_TP_PHASE` | To: `start`

**Action 5: Scene Show**
- Name: `TimerScene`
- Display As: Overlay, Blocking

> Scene handles both taps (start and stop). When the second tap occurs, the scene
> destroys itself and execution continues at Action 6.

**Action 6: Variable Set** (Do Maths: ON)
- Name: `%LD_TP_PRODUCED`
- To: `%LD_TP_END - %LD_TP_START`

**Action 7: JavaScriptlet** (Compute error)
```javascript
var target = parseInt(global('LD_TP_TARGET')) * 1000;
var produced = parseInt(global('LD_TP_PRODUCED'));
var error = produced - target;
var errorPct = ((error / target) * 100).toFixed(1);
setGlobal('LD_TP_ERROR', error);
setGlobal('LD_TP_ERROR_PCT', errorPct);
```

**Action 8: Write File**
- File: `Documents/LifeData/spool/cognition/time_prod_%TIMES.csv`
- Text: `%TIMES,%TIME,%TIMEZONE,%LD_TP_TARGET,%LD_TP_PRODUCED,%LD_TP_ERROR,%LD_TP_ERROR_PCT`
- Append: OFF

**Action 9: Flash**
- Text: `Target: %LD_TP_TARGET s | You: %LD_TP_PRODUCED ms | Error: %LD_TP_ERROR_PCT%`
- Duration: Long

**CSV Format:** `epoch,time,timezone,target_sec,produced_ms,error_ms,error_pct`

**Interpretation:**
- Negative error (underproduction) = internal clock running fast = high arousal/stimulants
- Positive error (overproduction) = internal clock running slow = low arousal/fatigue

---

## Task 321: Time_Estimation

**Module:** Cognition (NU)
**Purpose:** "I show you an interval. How long was it?" Reverse of Time_Production. Measures retrospective duration judgment.
**Duration:** ~10-25 seconds
**Trigger:** Widget / manual
**Scene Required:** `TimedDisplay`

### Step 1: Create Scene "TimedDisplay"

1. Open Tasker > **Scenes** tab
2. Tap **+** > Name: `TimedDisplay`
3. Set scene properties:
   - **Geometry:** Full screen
   - **Background Color:** A distinctive color (e.g., `#1565C0` — deep blue)
4. No interactive elements needed — this scene just displays a colored screen for a timed interval. The task controls when it appears and disappears.

### Step 2: Create Task "Time_Estimation"

**Action 1: JavaScriptlet** (Select random actual interval)
```javascript
var intervals = [3000, 7000, 12000, 20000];
var actual = intervals[Math.floor(Math.random() * intervals.length)];
setGlobal('LD_TE_ACTUAL', actual);
```

**Action 2: Flash**
- Text: `Watch...`
- Duration: Short

**Action 3: Wait**
- Milliseconds: 500

**Action 4: Scene Show**
- Name: `TimedDisplay`
- Display As: Overlay, Blocking, No Animation

**Action 5: Wait**
- Milliseconds: `%LD_TE_ACTUAL`

**Action 6: Scene Destroy**
- Name: `TimedDisplay`

**Action 7: Variable Query**
- Title: `How many seconds was that?`
- Variable: `%LD_TE_ESTIMATE`
- Default: (empty)

**Action 8: JavaScriptlet** (Compute error)
```javascript
var actual = parseInt(global('LD_TE_ACTUAL'));
var estimate = parseFloat(global('LD_TE_ESTIMATE')) * 1000;
var error = estimate - actual;
setGlobal('LD_TE_ESTIMATE_MS', Math.round(estimate));
setGlobal('LD_TE_ERROR', Math.round(error));
```

**Action 9: Write File**
- File: `Documents/LifeData/spool/cognition/time_est_%TIMES.csv`
- Text: `%TIMES,%TIME,%TIMEZONE,%LD_TE_ACTUAL,%LD_TE_ESTIMATE_MS,%LD_TE_ERROR`
- Append: OFF

**Action 10: Flash**
- Text: `Actual: %LD_TE_ACTUAL ms | You guessed: %LD_TE_ESTIMATE s`
- Duration: Long

**CSV Format:** `epoch,time,timezone,actual_ms,estimated_ms,error_ms`

**Interpretation:**
- Positive error (overestimation, "that felt longer") = retrospective time dilation = boredom/depression
- Negative error (underestimation, "that felt shorter") = time compression = engagement/flow

---

## Scene Creation Reference

### General Scene Tips

1. **Always test scenes independently** before connecting them to tasks. In the Scene Editor, use the play button to preview.

2. **Variable-based colors:** To dynamically set element colors, use the Element Set Colour action before Scene Show, or reference variables like `%LD_GNG_CIRCLE_COLOR` in the element properties.

3. **Blocking vs. Non-Blocking:** All cognitive probe scenes should use **Overlay, Blocking** display mode so the task pauses until the scene is destroyed.

4. **Scene Destroy timing:** If a scene should auto-close after a timeout (Go/NoGo), use a Wait action followed by Scene Destroy in the task. The scene's tap handler also calls Scene Destroy, creating a race condition that resolves correctly — whichever fires first wins.

### Scene Summary Table

| Scene Name | Used By | Elements | Tap Behavior |
|------------|---------|----------|--------------|
| `FullscreenColor` | Task 300 | 1 full-screen rectangle (dynamic color) | Tap records timestamp, destroys scene |
| `ChoiceRT` | Task 301 | 1 text (arrow), 2 buttons (LEFT/RIGHT) | Button tap records response + timestamp, destroys scene |
| `GoNoGoScene` | Task 302 | 1 circle (green/red dynamic) | Tap records response + timestamp, destroys scene |
| `TimerScene` | Task 320 | 1 text (instruction), 1 tap zone | First tap = start timer; second tap = stop timer, destroy scene |
| `TimedDisplay` | Task 321 | None (just colored background) | No tap handler — task controls display duration |

### Variable Reference (All Scene Tasks)

| Variable | Set By | Used By | Purpose |
|----------|--------|---------|---------|
| `%LD_RT_COLOR` | Task 300 (JS) | FullscreenColor scene | Background color for current trial |
| `%LD_RT_START` | Task 300 | Task 300 | Trial start timestamp (ms) |
| `%LD_RT_END` | FullscreenColor tap | Task 300 | Trial end timestamp (ms) |
| `%LD_CRT_ARROW` | Task 301 (JS) | ChoiceRT scene | Arrow direction display |
| `%LD_CRT_RESPONSE` | ChoiceRT button tap | Task 301 | Which button was pressed |
| `%LD_CRT_START/END` | Task 301 / ChoiceRT tap | Task 301 | Timing |
| `%LD_GNG_CIRCLE_COLOR` | Task 302 (JS) | GoNoGoScene | Circle color (green/red) |
| `%LD_GNG_RESPONDED` | GoNoGoScene tap | Task 302 | Whether user tapped (1) or not (0) |
| `%LD_GNG_START/END` | Task 302 / scene tap | Task 302 | Timing |
| `%LD_TP_PHASE` | Task 320 | TimerScene tap | Current phase (start/running) |
| `%LD_TP_START/END` | TimerScene taps | Task 320 | Production interval timing |

---

## Deployment Checklist

### Week 1
- [ ] Create `FullscreenColor` scene
- [ ] Create Task 300 (Simple_RT)
- [ ] Create widget for Simple_RT
- [ ] Test: run 3 trials, verify CSV appears in `spool/cognition/`
- [ ] Verify CSV syncs to desktop via Syncthing

### Week 2
- [ ] Create Task 320 (Time_Production) + `TimerScene`
- [ ] Create Task 321 (Time_Estimation) + `TimedDisplay`
- [ ] Import Task 310 (Digit_Span) from XML list
- [ ] Test all three independently

### Week 3
- [ ] Import Task 330 (Typing_Speed) from XML list
- [ ] Create Task 340 (Cognitive_Battery) or import from XML
- [ ] Test full battery chain (300 > 310 > 320 > 330)

### Week 4
- [ ] Create `ChoiceRT` scene
- [ ] Create Task 301 (Choice_RT)
- [ ] Create `GoNoGoScene`
- [ ] Create Task 302 (Go_NoGo)
- [ ] Test all cognitive probes

### Ongoing
- [ ] Monitor battery impact (should be negligible — all manual trigger)
- [ ] After 14 days of data: verify desktop parsers produce valid Events
- [ ] After 14 days: cognitive_load_index derived metric should have enough baseline

---

## Troubleshooting

### Scene doesn't respond to taps
- Ensure the tap zone element covers the full scene area
- Check that tap actions are assigned to the correct element
- Verify "Display As: Overlay, Blocking" is set in Scene Show

### %TIMEMS returns wrong values
- `%TIMEMS` is milliseconds since midnight, not Unix epoch. This is correct for computing deltas within a single day.
- If a trial crosses midnight (unlikely but possible), the delta will be negative. The desktop parser should handle this edge case.

### Variables not resolving in scene elements
- Scene element properties that reference variables (like `%LD_RT_COLOR`) must be set BEFORE Scene Show.
- Use the "Element Set Colour" Tasker action if dynamic variable binding doesn't work in scene properties.

### Go/NoGo scene doesn't auto-close on timeout
- The Wait + Scene Destroy in the task handles this. If the user taps before the wait expires, the scene is already destroyed when Scene Destroy fires — Tasker handles this gracefully (no error).

### CSV files not appearing
- Verify spool directories exist: `Documents/LifeData/spool/cognition/`
- Run the `LD_Create_Spool_Dirs` setup task from the XML list
- Check Tasker has storage permissions
