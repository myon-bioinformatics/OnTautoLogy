import Std

/-!
The exhaustive comparison behind tools/tautology.py:equivalent and
ontautology.py:entailment. An interpretation is a Boolean function of the
finite features mentioned by a rule. Parsing and evaluating the JSON syntax
are connected separately by Python tests; natural-language meaning is not
part of this model.
-/

namespace OnTautoLogy

abbrev Assignment (n : Nat) := Fin n → Bool

def extend {n : Nat} (head : Bool) (tail : Assignment n) : Assignment (n + 1) :=
  Fin.cases head tail

/-- Enumerate false before true, including the single empty assignment. -/
def assignments : (n : Nat) → List (Assignment n)
  | 0 => [fun bit => Fin.elim0 bit]
  | n + 1 => (assignments n).map (extend false) ++ (assignments n).map (extend true)

/-- Exhaustive coverage is required before absence of a counterexample is proof. -/
theorem assignments_complete (n : Nat) (row : Assignment n) : row ∈ assignments n := by
  induction n with
  | zero =>
    have empty : row = (fun bit => Fin.elim0 bit) := by
      funext bit
      exact Fin.elim0 bit
    simp [assignments, empty]
  | succ n ih =>
    let tail : Assignment n := fun bit => row bit.succ
    have decomposition : extend (row 0) tail = row := by
      funext bit
      refine Fin.cases ?_ (fun i => ?_) bit
      · rfl
      · rfl
    have covered := ih tail
    cases first : row 0 with
    | false =>
      apply List.mem_append_left
      apply List.mem_map.mpr
      exact ⟨tail, covered, by simpa [first] using decomposition⟩
    | true =>
      apply List.mem_append_right
      apply List.mem_map.mpr
      exact ⟨tail, covered, by simpa [first] using decomposition⟩

def difference {n : Nat} (left right : Assignment n → Bool) : Option (Assignment n) :=
  (assignments n).find? (fun row => left row != right row)

theorem difference_replays {n : Nat} (left right : Assignment n → Bool)
    (row : Assignment n) (found : difference left right = some row) :
    left row ≠ right row := by
  have unequal := List.find?_some found
  simpa using unequal

theorem equivalence_iff {n : Nat} (left right : Assignment n → Bool) :
    difference left right = none ↔ ∀ row, left row = right row := by
  simp only [difference, List.find?_eq_none]
  constructor
  · intro checked row
    simpa using checked row (assignments_complete n row)
  · intro equal row _
    simp [equal row]

def counterexample {n : Nat} (premises conclusion : Assignment n → Bool) : Option (Assignment n) :=
  (assignments n).find? (fun row => premises row && !conclusion row)

def consistent {n : Nat} (premises : Assignment n → Bool) : Bool :=
  (assignments n).any premises

theorem counterexample_replays {n : Nat} (premises conclusion : Assignment n → Bool)
    (row : Assignment n) (found : counterexample premises conclusion = some row) :
    premises row = true ∧ conclusion row = false := by
  have rejected := List.find?_some found
  simpa using rejected

theorem no_counterexample_iff {n : Nat} (premises conclusion : Assignment n → Bool) :
    counterexample premises conclusion = none ↔
      ∀ row, premises row = true → conclusion row = true := by
  simp only [counterexample, List.find?_eq_none]
  constructor
  · intro checked row accepted
    have h := checked row (assignments_complete n row)
    simpa [accepted] using h
  · intro consequence row _
    cases hp : premises row with
    | false => simp
    | true => simp [consequence row hp]

theorem consistent_iff {n : Nat} (premises : Assignment n → Bool) :
    consistent premises = true ↔ ∃ row, premises row = true := by
  simp only [consistent, List.any_eq_true]
  constructor
  · rintro ⟨row, _, accepted⟩
    exact ⟨row, accepted⟩
  · rintro ⟨row, accepted⟩
    exact ⟨row, assignments_complete n row, accepted⟩

inductive Verdict where
  | counterexample
  | entailed
  | inconsistentPremises
  deriving DecidableEq

/-- Mirrors entailment's three outcomes; inconsistency is not usable entailment. -/
def infer {n : Nat} (premises conclusion : Assignment n → Bool) : Verdict :=
  if (counterexample premises conclusion).isSome then .counterexample
  else if consistent premises then .entailed else .inconsistentPremises

theorem entailed_iff {n : Nat} (premises conclusion : Assignment n → Bool) :
    infer premises conclusion = .entailed ↔
      (∃ row, premises row = true) ∧
      (∀ row, premises row = true → conclusion row = true) := by
  rw [← consistent_iff premises, ← no_counterexample_iff premises conclusion]
  unfold infer
  cases he : counterexample premises conclusion <;> cases hc : consistent premises <;> simp_all

theorem inconsistent_iff {n : Nat} (premises conclusion : Assignment n → Bool) :
    infer premises conclusion = .inconsistentPremises ↔
      ∀ row, premises row = false := by
  constructor
  · intro reported row
    have noSupport : consistent premises = false := by
      unfold infer at reported
      cases he : counterexample premises conclusion <;> cases hc : consistent premises <;> simp_all
    have noTrue : ¬ ∃ row, premises row = true := by
      intro yes
      have yesSupport := (consistent_iff premises).mpr yes
      simp [noSupport] at yesSupport
    cases hr : premises row
    · rfl
    · exact False.elim (noTrue ⟨row, hr⟩)
  · intro impossible
    have noCounterexample : counterexample premises conclusion = none := by
      apply (no_counterexample_iff premises conclusion).mpr
      intro row accepted
      simp [impossible row] at accepted
    have noSupport : consistent premises = false := by
      simp [consistent, impossible]
    simp [infer, noCounterexample, noSupport]

end OnTautoLogy
