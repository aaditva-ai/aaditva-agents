import { Routes, Route } from "react-router-dom";
import { SignInGate } from "./auth/SignInGate";
import { HomeRoute } from "./routes/HomeRoute";
import { CampaignRoute } from "./routes/CampaignRoute";
import "./App.css";

function App() {
  return (
    <SignInGate>
      <Routes>
        <Route path="/" element={<HomeRoute />} />
        <Route path="/c/:sessionId" element={<CampaignRoute />} />
      </Routes>
    </SignInGate>
  );
}

export default App;
