import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(e) { return { error: e }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{padding:"2rem",fontFamily:"monospace",color:"#c0392b",background:"#fff",maxWidth:"600px",margin:"2rem auto",border:"1px solid #c0392b",borderRadius:"8px"}}>
          <b>FarmIQ crashed on startup</b><br/><br/>
          <code style={{whiteSpace:"pre-wrap"}}>{String(this.state.error?.stack || this.state.error)}</code>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
