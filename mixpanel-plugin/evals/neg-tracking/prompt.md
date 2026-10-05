---
description: Tracking implementation in app code is not an analysis task. The mixpanelyst skill should not fire.
tags: [offline]
max_turns: 15
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill]
---

Add Mixpanel tracking to my React signup form. Track when the form is viewed, when it is submitted, and when signup fails (with the error message). Reply with the updated component; do not create files.

```jsx
import { useState } from "react";

export function SignupForm({ onSignup }) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    try {
      await onSignup(email);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <input value={email} onChange={(e) => setEmail(e.target.value)} />
      <button type="submit">Sign up</button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
```
