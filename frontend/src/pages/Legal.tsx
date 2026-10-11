import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon } from "@/components/Icon";

function LegalPage({ title, children }: { title: string; children: ReactNode }) {
  return <div className="legal-page">
    <div className="onboarding-brand"><div className="brand-mark"><Icon name="play" size={16}/></div><span>ClipRelay</span></div>
    <h1>{title}</h1>
    <div className="draft-note">Draft text. Replace it with the wording agreed with the client before the app is used in production.</div>
    {children}
    <p style={{ marginTop: 32 }}><Link to="/">Back to ClipRelay</Link> · <Link to="/terms">Terms of Use</Link> · <Link to="/privacy">Privacy Policy</Link></p>
  </div>;
}

export function Terms() {
  return <LegalPage title="Terms of Use">
    <h2>1. What ClipRelay is</h2>
    <p>ClipRelay is a private tool operated for one client. It watches the client's own YouTube channels and republishes their new short-form uploads to the client's TikTok accounts. There is no public sign-up; accounts are created by a workspace owner.</p>
    <h2>2. Only the client's own content</h2>
    <p>Only add channels whose videos the client has the right to republish. Reposting other people's videos may lead to copyright strikes and the termination of TikTok accounts.</p>
    <h2>3. Your account</h2>
    <p>Keep your password private. What is done under your sign-in — adding channels, approving or rejecting videos, changing settings — is recorded with your account and the time.</p>
    <h2>4. Third-party platforms</h2>
    <p>ClipRelay depends on YouTube and TikTok. Their terms and policies apply to the content and to the connected accounts, and they can change or limit their services at any time. Reach on republished videos is not guaranteed.</p>
    <h2>5. Availability</h2>
    <p>The tool is provided as is. Downloads, edits or uploads can fail, and failed videos are shown in the app so that they can be retried.</p>
  </LegalPage>;
}

export function Privacy() {
  return <LegalPage title="Privacy Policy">
    <h2>1. What is stored</h2>
    <ul>
      <li>Operator accounts: name, email address, a hashed password, and the time the terms were accepted.</li>
      <li>Connected TikTok accounts: display name, profile picture, and access tokens, which are stored encrypted.</li>
      <li>Videos from the monitored channels: titles, descriptions, tags, thumbnails, and the video files while they are being processed.</li>
      <li>An activity log: what was detected, published or skipped, and who changed which setting.</li>
    </ul>
    <h2>2. How it is used</h2>
    <p>The data is used only to run the service: detecting uploads, editing them, writing captions and publishing to TikTok. Video titles, descriptions and tags are sent to the configured AI model to write captions.</p>
    <h2>3. How long it is kept</h2>
    <p>Video files are deleted a set number of days after publishing (7 by default). The records of what was published are kept as the history of the service.</p>
    <h2>4. Who can see it</h2>
    <p>Only the operators of this workspace. Data is shared with YouTube, TikTok and the AI model provider only as far as the service needs.</p>
    <h2>5. Removing data</h2>
    <p>A workspace owner can disconnect a TikTok account, remove a channel, or remove an operator at any time in the app.</p>
  </LegalPage>;
}
