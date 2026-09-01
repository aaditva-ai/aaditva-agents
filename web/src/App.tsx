import { Routes, Route } from "react-router-dom";
import { SignInGate } from "./auth/SignInGate";
import { Layout } from "./components/Layout";
import { HomeRoute } from "./routes/HomeRoute";
import { CampaignRoute } from "./routes/CampaignRoute";

function App() {
  return (
    <SignInGate>
      <Layout>
        <Routes>
          <Route path="/" element={<HomeRoute />} />
          <Route path="/c/:sessionId" element={<CampaignRoute />} />
        </Routes>
      </Layout>
    </SignInGate>
  );
}

export default App;
