import React, { useState } from "react";
import { AuthProvider } from "./context/AuthContext";
import { useAuth } from "./hooks/useAuth";
import Navbar from "./components/Navbar";
import LoginPage from "./pages/LoginPage";
import DashboardMapPage from "./pages/DashboardMapPage";
import SearchPage from "./pages/SearchPage";
import CamerasPage from "./pages/CamerasPage";
import JobsPage from "./pages/JobsPage";
import AlertsPage from "./pages/AlertsPage";

function MainContent() {
  const { isAuthenticated } = useAuth();
  const [activeTab, setActiveTab] = useState("dashboard");
  const [targetPlate, setTargetPlate] = useState(null);

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  const handleTracePlate = (plate) => {
    setTargetPlate(plate);
    setActiveTab("dashboard");
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 flex flex-col font-sans">
      <Navbar activeTab={activeTab} onSelectTab={setActiveTab} />

      <main className="flex-1 flex flex-col">
        {activeTab === "dashboard" && (
          <DashboardMapPage
            initialSearchPlate={targetPlate}
            onPlateSelect={(p) => setTargetPlate(p)}
          />
        )}
        {activeTab === "search" && <SearchPage onTracePlate={handleTracePlate} />}
        {activeTab === "cameras" && <CamerasPage />}
        {activeTab === "jobs" && <JobsPage />}
        {activeTab === "alerts" && <AlertsPage />}
      </main>
    </div>
  );
}

export function App() {
  return (
    <AuthProvider>
      <MainContent />
    </AuthProvider>
  );
}

export default App;
